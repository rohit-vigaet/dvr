


# Noah Cubert July 2020 Intern: 
# All comments by this user will be denoted with an NC before the comment.
# For a single line comment denoted by '#' the following example will occur:
# # NC: This is a test comment
# For a block comment the following example will occur:
# '''
# NC: This is a test block comment
# '''

import os
import platform
import sys

from PyQt5 import QtCore, QtWidgets
from typing import Callable, Dict, List, Tuple, Union

from scorhe_server import server
from scorhe_aquisition_tools import bundle
from scorhe_aquisition_tools.scorhe_launcher_gui import SettingsWindow

#*********************** NC added
import utils
HOLDER = ""
saveFilePath = r"save_location_settings.txt"
if platform.system() == 'Linux':
    saveFilePath = r"save_location_settings_linux.txt"
#***************************

class Setter:
    """
    Setter object helps the user modify the settings of the experiment.
    """
   
    def __init__(self,
                 setSettings: Callable[[], None],
                 controllerThread: server.CameraServerController,
                 settings: Dict[str, Union[str, int, float, Tuple, Dict, List, bool]],
                 camPorts: Dict[str, int],
                 updater,
                 camUpdate: Callable[[], None],
                 cageUpdate: Callable[[], None],
                 ):
        self.setSettings = setSettings
        self.controllerThread = controllerThread  # type: server.CameraServerController
        self.camPorts = camPorts
        self.updater = updater
        self.camUpdate = camUpdate
        self.cageUpdate = cageUpdate
        
        # Create GUI
        self.settingsWindow = SettingsWindow()
        self.settingsWindow.show()
        # Reference to GUI attributes
        self.buttons = self.settingsWindow.buttons
        self.text = self.settingsWindow.text
        self.settings = settings  # type: Dict[str, Union[str, int, float, Tuple, Dict, List, bool]]
     
        self.updateSettings()
        self.settingsWindow.show()

    def runSettings(self) -> None:
        """
        Connect all the buttons of the GUI window and run settings update
        """
        self.buttons["okay"].clicked.connect(self.saveSettings)
        self.buttons["default"].clicked.connect(self.setDefaultSettings)
        self.buttons["names"].clicked.connect(self.setCamNames)
        self.buttons["compression"].valueChanged.connect(self.compressionChanged)
        self.buttons["compression"].setValue(self.settings["compression"])
        self.compressionChanged(self.settings["compression"])



        self.settingsWindow.saveLocationOpener.clicked.connect(self.selectSaveLocationSettings)
        #self.settingsWindow.saveLocationLineEdit.setPlaceholderText('default: '+ utils.APPDATA_DIR)
        self.updateSettings()

    def compressionChanged(self, new: int) -> None:
        """This function is called when the compression setting is changed.

        This updates the text in the setting for the compression.
        """
        self.text["compressionLabel"].setText("Compression: {}x".format(new))

    def setCamNames(self) -> None:
        """
        A listener that opens the bundling system to assign cameras to names.
        """
        bundler = bundle.Bundler(self.settings['camMap'], self.controllerThread, self.camPorts,
                                 self.updater, self.camUpdate, self.settings['grouptype'])
        bundler.runBundle()

    def setDefaultSettings(self) -> None:
        """
        Set default settings
        """
        self.settings = {'compression': 1, 'color': True, 'iso': '0', 'len': 2, 'reso': '640x480',
                         'vflip': {'camera': {}, 'default': True}, 'fps': 30, 
                         'autogain': True, 'gain': 0,
                         'camMap': {'name': {}, 'camera': {}},
                         'rotation': {'camera': {}, 'default': 0},
                         'zoom location': {'camera': {}, 'default': (0, 0)},
                         'zoom dimension': (1290, 720),
                         'pushUpdates': False, 'grouptype': 'SCORHE',
                         'baseDirectory': ''
                         }
       
        self.updateSettings()

    def updateSettings(self) -> None:
        """
        Fill out the settings panel with the current settings
        """
        self.text["clip len"].setValue(self.settings['len'])
        self.text["fps"].setValue(self.settings['fps'])
        self.text["gain"].setValue(self.settings['gain'])
        index = self.buttons["iso"].findText(self.settings['iso'], QtCore.Qt.MatchFixedString)
        self.buttons["iso"].setCurrentIndex(index)
        self.buttons["compression"].setValue(self.settings['compression'])
        self.buttons["color"].setChecked(self.settings['color'])
        self.buttons["vflip"].setChecked(bool(id(self.settings['vflip']) % 2))
        self.buttons["autogain"].setChecked(self.settings['autogain'])
        
        #NC: Addition
        #self.buttons["sd"].setChecked(bool(id(self.settings['zoom dimension']) % 2))
        index = self.buttons["reso"].findText(self.settings['reso'], QtCore.Qt.MatchFixedString)
        self.buttons["reso"].setCurrentIndex(index)
        self.settingsWindow.saveLocationLineEdit.setPlaceholderText('default: '+ utils.APPDATA_DIR)

      
    def saveSettings(self) -> None:
        """
        Set the settings from GUI user input to software
        """
        self.settings['len'] = self.text["clip len"].value()
        self.settings['fps'] = self.text["fps"].value()
        self.settings['iso'] = self.buttons["iso"].currentText()
        self.settings['compression'] = self.buttons["compression"].value()
        self.settings['color'] = self.buttons["color"].isChecked()
        self.settings['vflip']['default'] = self.buttons["vflip"].isChecked() # NC edi


        self.settings['reso'] = self.buttons["reso"].currentText()
        substr = self.buttons["reso"].currentText().split('x', 1)
        self.settings['zoom dimension'] = (int(substr[0]), int(substr[1]))

        
        
        self.settings['autogain'] = self.buttons['autogain'].isChecked()
        self.settings['gain'] = self.text["gain"].value()
        self.settingsWindow.close()
        self.setSettings()
        self.cageUpdate()
        self.settingsWindow = None


    def selectSaveLocationSettings(self) -> str:
        """
        Sets where the file will be saved
        """
      
        tempFile = QtWidgets.QFileDialog.getExistingDirectory(self.settingsWindow, 'Select a directory', os.getenv('USERPROFILE'))
        
        HOLDER = tempFile
        # NC addition
        # write the file name holder to the save_location_settings.txt or save_location_settings_linux.txt if on linux os
      
        try:
            save_file = open(saveFilePath, "w")  # should write to this file
            save_file.write(tempFile)
        except IOError:
            print("IOError IN CAM_SET.py\n")
        except FileNotFoundError:
            print("File not found ERROR IN CAM_SET.py\n")
        finally:
            save_file.close()


        if tempFile:
            self.settingsWindow.saveLocationLineEdit.setText(tempFile)
            return tempFile
        else:
            return ""

    




