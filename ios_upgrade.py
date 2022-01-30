#! /usr/bin/env python

'''
Script to automate IOS upgrade of Cisco switches. Assumes that the new IOS
file has already been copied to all switches/supervisors.

Libraries required: netmiko, getpass, time

Original Version: Stacy Sherman 8/24/16

'''

from netmiko import ConnectHandler
from getpass import getpass
import re
import time


def select_type():
    '''
    Allows user to select the type of device being upgraded to determine if it's
    a single device, multiple supervisor chassis, or stack of switches
    '''
    print "\n\n"
    print "----------------------------------------------------------"
    print "|                                                        |"
    print "|                  IOS Upgrade Tool                      |"
    print "|                                                        |"
    print "----------------------------------------------------------"
    print "\nPlease select the type of upgrade you're doing:\n"
    print "(1) Standalone router or switch with one supervisor"
    print "(2) Chassis switch with two supervisors"
    print "(3) Stack of switches\n"
    ans = raw_input("===> ")
    while ans not in ['1', '2', '3']:
        ans = raw_input("\nPlease select 1, 2 or 3 ===> ")
    if ans == '1':
        print "\n NOTE: Standalone upgrade not implemented yet. Sorry.\n"
        return 'standalone'
    elif ans == '2':
        return 'multisup'
    elif ans == '3':
        print "\n NOTE: Stack upgrade not implemented yet. Sorry. \n"
        return 'stack'


def get_dev_info():
    '''
    Gathers the IP address, username and password for the switch from the user
    and returns a dictionary containing the needed information.
    For now, it assumes the device type is cisco_ios (not ASA, Juniper, etc)
    '''
    ip_addr = raw_input("\nIP address of device to upgrade: ")
    username = raw_input("\nUser name: ")
    pwd = getpass()
    net_device = {
        'device_type': 'cisco_ios',
        'ip': ip_addr,
        'username': username,
        'password': pwd,
    }
    return net_device


def device_connect(net_device):
    '''
    Connects to device, performs error checkig (in the future) and prints out
    confirmation information
    '''

    target_dev = ConnectHandler(**net_device)  # Connect to device
    hostname = target_dev.find_prompt().strip('#')
    print "\nConnected to: %s at IP: %s \n" % (hostname, net_device['ip'])
    if target_dev.check_enable_mode:
        print "Enable mode verified\n"
    else:
        en = raw_input("You\'re not in enable mode. Enter \'y\' for enable: ")
        if en == 'y' or en == 'Y':
            target_dev.enable()
            if not target_dev.check_enable_mode:
                print "Unable to enter enable mode."
    a = target_dev.disable_paging
    return target_dev


def select_ios(target_dev):
    '''
    Lists the available '.bin' files from the directory and allows the user to
    choose which file to upgrade to
    '''
    d = target_dev.send_command("dir")  # Get the dir listing
    fs = re.findall('\S+:\/', d)  # Get the file system
    fs = fs[0].strip('/')  # Reduce the list to a string
    file_list = re.findall('\S+.bin', d)  # Get list of all .bin files
    n = 1
    print ".bin Files Available in primary file system", fs
    print "==================================================================="
    for binfile in file_list:
        print n, ": ", binfile
        n += 1
    ios_choice = int(raw_input("\nType the # of the file to upgrade to: "))
    new_ios = file_list[ios_choice - 1]
    print "\nPlease ensure this ios has been copied to all other supervisors or switches."
    ans = ''
    while ans not in ['Y', 'y', 'N', 'n']:
        ans = raw_input("\n Would you like to see a listing of all file systems? (y/n) ")
    if ans in ['Y', 'y']:
        d_all = target_dev.send_command("dir all-filesystems")
        time.sleep(10)
        print d_all
    return fs + new_ios


def set_bootvar_multisup(target_dev, bootvar, log):
    '''
    Sets the boot variable on a chassis based Cisco switch with two
    supervisor modules.
    '''
    print "\nOK. Starting upgrade process..."
    print "\nEntering config mode..."
    log += target_dev.config_mode()
    print "\nClearing old boot variable..."
    log += target_dev.send_command("no boot system")
    bootcmd = "boot system " + bootvar
    print "\nSetting new boot variable to: ", bootvar
    log += target_dev.send_command(bootcmd)
    print "\nExiting config mode..."
    log += target_dev.exit_config_mode()
    print "\nSaving config..."
    log += target_dev.send_command("write mem")
    time.sleep(22)
    print "Getting new boot settings..."
    newboot = target_dev.send_command("show bootvar | inc BOOT variable =")
    log += newboot
    print "newboot:", newboot
    nb = newboot.split('\n')
    print "nb: ", nb
    active_boot = nb[0]
    standby_boot = nb[1]
    print "\nVerifying active sup boot variable..."
    if bootvar in active_boot:
        print "\n %s is in BOOT variable" % bootvar
    else:
        print "\n %s is NOT in BOOT variable, aborting upgrade" % bootvar
        return 0
    print "\nVerifying standby sup boot variable..."
    if bootvar in standby_boot:
        print "\n %s is in standby BOOT variable" % bootvar
    else:
        print "\n %s is NOT in standby BOOT variable, aborting upgrade" % bootvar
        return 0
    return 1


def analyze_sups_multisup(target_dev):
    '''
    Checks to see which slot is active and which is standby. Returns the active
    and standby slot numbers and the status of the standby supervisor.
    '''

    print "\nAnalyzing supervisor redundancy..."
    active_slot = '0'
    standby_slot = '0'
    standby_status = 'none'
    out1 = target_dev.send_command("sh redundancy | inc Active Location =").strip()
    out2 = target_dev.send_command("sh redundancy | inc Standby Location =").strip()
    active_slot = out1[-1]
    standby_slot = out2[-1]
    cmd = "show module " + standby_slot
    out = target_dev.send_command(cmd)
    if "(Other)" in out:
        standby_status = 'other'
    elif "(Cold)" in out:
        standby_status = 'cold'
    elif "(Hot)" in out:
        standby_status = 'hot'
    print "\nActive supervisor is in slot: ", active_slot
    print "\nStandby supervisor is in slot: ", standby_slot
    return active_slot, standby_slot, standby_status


def reload_sup(target_dev, slot, log):
    '''
    Reloads the given supervisor module, waits until it reboots into standby
    hot.
    '''
    print "\nEnsuring module %s is in standby hot" % slot
    cmd = "show module " + slot
    out = target_dev.send_command(cmd)
    if not "(Hot)" in out:
        print "\nUnable to verify module %s is standby hot" % slot
        return 0
    else:
        reload_cmd = "hw-module module %s reset" % slot
        log += target_dev.send_command(reload_cmd)
        log += target_dev.send_command('y')
        return 1


def mon_sup_reload(target_dev, slot, log):
    '''
    Monitors a supervisor while rebooting and waits until it has returned to
    standby cold or hot status after IOS upgrade. Checks every minute for 30 minutes
    and will give up after that.
    '''
    ready = 0
    mins = 0
    cmd = "show module " + slot
    print "\nMonitoring supervisor in slot %s" % slot
    while ready == 0 and mins <= 30:
        print "\nWaiting a minute. It's been %d minutes since module reload" % mins
        time.sleep(60)
        mins += 1
        print "\nChecking supervisor status..."
        out = target_dev.send_command(cmd)
        log += out
        if "(Cold)" in out or "(Hot)" in out:
            ready = 1
            return ready
        else:
            ready = 0
    print "It has been %d minutes since reboot & still not acive hot. Giving up" % mins
    return 0


def force_switchover(target_dev, standby_slot, log):
    '''
    Performs a force switchover from the active to the standby supervisor.
    '''
    cmd = "show module " + standby_slot
    print "\nChecking supervisor status..."
    out = target_dev.send_command(cmd)
    log += out
    if "(Cold)" in out or "(Hot)" in out:
        print "\nSupervisor in slot %s is standby hot or cold. Ready to force switchover..." % standby_slot
        print "\nThis will disconnect the Upgrade Tool and cause DOWN TIME on the switch."
        print "\nType 'reload' to proceed with the force_switchover and associated down time."
        print "\nor type 'quit' to abort the process"
        ans = raw_input("\n====>")
        ans = ans.lower()
        if ans not in ['reload', 'quit']:
            ans = raw_input("Please type 'reload' or 'quit'")
            ans = ans.lower()
        if ans == 'reload':
            print "\nInitiating force_switchover NOW. It will be a 5 minute wait and outage"
            print "until the upgrade tool can reconnect to the device.\n"
            out = target_dev.send_command("redundancy force-switchover")
            out += target_dev.send_command("y")
            log += out  # Session will disconnect at this point
            return 1
        else:
            print "OK. Exiting the upgrade."
            print "Please note that the boot variable is still set to the new IOS"
            print "and the supervisors may be running different versions of code."
            print "These will need to be fixed manually."
            return 0
    else:
        print "Standby supervisor not ready. Exiting"
        return 0


def final_check(target_dev, bootvar, log):
    '''
    Perform final check to ensure the correct version is running and we have
    one active and one standby hot supervisor.
    '''

    print "\nSecond supervisor has come back up. Performing final check."
    print "\nChecking that correct boot file is in 'show version'"
    shver = target_dev.send_command("show version")
    if bootvar in shver:
        print "\nBoot file in show version matches upgrade boot file."
        print "\n Checking for a 'Standby Hot' supervisor"
        active_slot, standby_slot, standby_status = analyze_sups_multisup(target_dev)
        if standby_status == 'hot':
            print "\nVerified the standby supervisor is 'Hot'"
            print "This means that the standby has come up all the way and"
            print "the software versions match."
        else:
            print "\nStandby supervisor status is %s. Please investigate." % standby_status
    else:
        print "\nUnable to find the correct boot file in 'show version'. Please investigate."


def upgrade_multisup(target_dev, net_device, bootvar, log):
    '''
    Perform the IOS upgrade on a multi-supervisor chassis switch.
    '''
    print "\n Ready to begin upgrade process. Type 'upgrade' to start or 'quit' to cancel the upgade\n"
    ans = raw_input("====>")
    ans = ans.lower()
    while ans not in ['upgrade', 'quit']:
        ans = raw_input("Please type 'upgrade' or 'quit'")
        ans = ans.lower()
    if ans in ['upgrade']:
        bv = set_bootvar_multisup(target_dev, bootvar, log)
        if bv:
            active_slot, standby_slot, standby_status = analyze_sups_multisup(target_dev)
        else:
            print "\nCould not set boot variable"
        if active_slot and standby_slot:
            rel = reload_sup(target_dev, standby_slot, log)
        else:
            print "\nCould not determine both active and standby slots"
        if rel:
            sup_ready = mon_sup_reload(target_dev, standby_slot, log)
        else:
            print "Supervisor not standby hot or reload aborted"
        if sup_ready:
            fs = force_switchover(target_dev, standby_slot, log)
        else:
            print "Reloaded supervisor never came back to active"
        if fs:
            print "\nWaiting 5 minutes to reconnect. Zzzz..."  # Reconnect to device
            time.sleep(300)
            print "\nReconnecting...\n"
            target_dev = device_connect(net_device)
            old_active_slot = active_slot  # Re-check supervisor status
            old_stdby_slot = standby_slot
            active_slot, standby_slot, standby_status = analyze_sups_multisup(target_dev)
            if active_slot == old_stdby_slot:
                print "Switchover successful. Slot %s now active" % active_slot
                print "Waiting for standby to become standby hot"
                print "This may take up to 15 minutes."
                sup_ready = mon_sup_reload(target_dev, old_active_slot, log)
                if sup_ready:
                    fc = final_check(target_dev, bootvar, log)
                else:
                    print "Could not verify standby supervisor as ready. Please investigate."
                if fc:
                    print "\n ===== Upgrade Completed successfully! =====\n\n"
                    return 0
                else:
                    print "\n ===== Errors were encountered during the upgrade =====\n\n"
                    return 1


def main():
    dev_type = select_type()  # Select the type of upgrade
    if dev_type == 'standalone' or dev_type == 'stack':
        return 1  # Standalone and stack not implemented yet
    net_device = get_dev_info()  # Get the device info
    target_dev = device_connect(net_device)  # Connect to device
    log = "=======Upgrade Log======\n Start Time: "
    log += target_dev.send_command("show clock")
    bootvar = select_ios(target_dev)  # Get file system & new ios
    print "\n Will upgrade to %s" % bootvar
    if dev_type == 'multisup':
        ms = upgrade_multisup(target_dev, net_device, bootvar, log)
    if ms == '0':
        return 0
    else:
        return 1


if __name__ == '__main__':
    main()
