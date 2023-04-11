"""A utilty module for use throughout the acquisition package"""
# Note that this is where settings made by the user via the GUI launched by launcher.py are saved.
# These settings are automatically saved to C:\User\[UserNAME]\Downloads\SCHORHE directory, 
# and if such a directory doesn't exist it will create one



import argparse
import os
import getpass
import platform
import re
import shlex
import shutil
import subprocess
import sys
import time
from scorhe_aquisition_tools import cam_set




"""
Make a txt file, which for one line (the first line) stores a path variable (User/ti.....)
This storage will happen via cam_set.py and will only happen in cam_set.py if the line is empty


if that line is empty (in other words EOF):
    APPDATA_DIR = os.path.join(os.getenv("USERPROFILE"), "Downloads", "SCHORE", "")
    if not os.path.isdir(APPDATA_DIR):
        os.makedirs(APPDATA_DIR)
else:
    APPDATA_DIR = os.path.join( IN HERE INSERT THE FILE PATH via the txt file)
    ADD EXCEPTION STATEMENT HANDELER

"""

if platform.system() == 'Windows':
    if cam_set.HOLDER:
        APPDATA_DIR = os.path.join(cam_set.HOLDER)
    else:
        APPDATA_DIR = os.path.join(os.getenv("USERPROFILE"), "Downloads", "SCORHE", "")
        if not os.path.isdir(APPDATA_DIR):
            os.makedirs(APPDATA_DIR)
        file = open(r"save_location_settings.txt", "w")
        file.write(APPDATA_DIR)
        file.close()
elif platform.system() == 'Linux':
    if cam_set.HOLDER:
        APPDATA_DIR = os.path.join(cam_set.HOLDER)
    else:
        
        #APPDATA_DIR = os.path.join(os.environ['HOME'], getpass.getuser(), "SCORHE", "")
        APPDATA_DIR = os.path.join(os.environ['HOME'], "Downloads", "SCORHE", "")
        if not os.path.isdir(APPDATA_DIR):
            os.makedirs(APPDATA_DIR)
        file = open(r"save_location_settings_linux.txt", "w")
        file.write(APPDATA_DIR)
        file.close()
else:
    raise OSError('SCORHE Acquisition does not support your system: {}'.format(platform.system())) 



def expFilePath() -> str:
    """Gets the file path for the experiment's json file."""
    #APPDATA_DIR = saveFileSettings()
    return os.path.join(APPDATA_DIR, "exp.json")


def settingsFilePath() -> str:
    """Gets the file path for the program's settings json file."""
    #APPDATA_DIR = saveFileSettings()
    return os.path.join(APPDATA_DIR, "settings.json")


def convertTimestamp(t: float) -> str:
    """Converts numeric time to a string that MATLAB can read.

    t is a double representing the elapsed number of seconds since the epoch.
    The resulting string shows the year, month, day, hour, minute, and second.
    The second is followed by a decimal point with three digit precision.

    :param t: the time to convert, in seconds since the epoch
    :return: A string representation of the given time in local time.
    """
    return time.strftime('%Y-%m-%d %Hh%Mm%S.{}s'.format(
            str(int(round(t * 1000)) % 1000).rjust(3, '0')),
            time.localtime(t))


def truncateFilename(filename: str) -> str:
    """Return the part of a video filename containing the time, camera ID and suffix.

    This is used to remove a bit of clutter from the console.

    :param filename: A filename for a video, formatted with no spaces in the
        time or camera id, and otherwise looks like this:
        ``"[{misc} ]{time} {id}.{ext}"``.
    :return: A string containing the time an camera id of a file, separated by
        a space.
    """
    return ' '.join(filename.split(' ')[-2:])


