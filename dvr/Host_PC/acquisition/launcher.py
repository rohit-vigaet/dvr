"""
The SCORHE launcher is a program that provides the logic for the front end user facing code.
This file exists to link the frontend GUI code (which is a mess due to the
fact it was automatically generated) to the backend server code. Both the server and the
GUI are instantiated within its logic and will be utilized to create a good user experience.
Though its logic and GUI buttons, a user will be able to start recording, previewing all cameras
on the network. The user will also be able to group cameras and schedule experiments.

# SCORHE Launcher, Author: Joshua Lehman, 2017
"""


"""
Noah Cubert_July 2020 Intern: 
All comments by this user will be denoted with an NC before the comment.
For a single line comment denoted by '#' the following example will occur:
# NC: This is a test comment
For a block comment the following example will occur:
'''
NC: This is a test block comment
'''
"""
import datetime
# for some reason, this is needed to make sure the server doesnt crash.
# noinspection PyUnresolvedReferences
import encodings.idna
import json
import logging
import os
import sys
import threading
import time
from functools import partial

from PyQt5 import QtWidgets

from typing import Dict, List, Union, Optional
try:
    import sip
except ImportError:
    sip = None

import utils
from scorhe_aquisition_tools import cam_set, exp_updater, \
    updater, gplayer
from scorhe_aquisition_tools.scorhe_launcher_gui import LegendGui, AcquisitionWindow
from scorhe_server import server, gpac

logger = logging.getLogger(__name__)
WAITCLICKED = False

class LaunchObject:
    """This class launches the whole server experiences.

    It first instantiates an instance of CameraServer, and then launches the
    required GUIs for user interaction.

    Q widgets are not threadsafe, so this can't be a thread.
    """
    # Somehow using slots breaks time.sleep in startLauncher and I don't know why
    # __slots__ = ('argv', 'camPorts', 'activeStreams', 'settings', 'expInfo',
    #              'players', 'controllerThread', 'updater', 'setter',
    #              'expUpdater', 'cameras', 'csv', 'buttons', 'cameraPickers',
    #              'playersGroup', 'text', 'window', 'time', 'recording',
    #              'addedExp', 'timed', 'saveLocation', 'endRunThread',
    #              'startRunThread',
    #              )
  
    def __init__(self, argv: List[str], window: AcquisitionWindow):
        self.camPorts = {}
        """Dictionary to map camera to streaming port.
        :type: Dict[str, int]
        """

        self.activeStreams = {"topLeftSelect": "", "topRightSelect": "",
                              "botLeftSelect": "", "botRightSelect": ""}
        """List reference to streams that are being shown in players.
        
        Maps selector name to selected camera id.
        :type: Dict[str, str]
        """

        self.settings = {}
        """Dictionary of settings for the system.
        
        :type settings: Dict[str: Union[int, str, float, List, Dict[str, Dict]]]
        """

        self.expInfo = {}
        """A dictionary used to store the details needed for an experiment.
        
        This includes its name, save location, start and end times, among other
        things. 
        
        This dictionary is given to the expUpdate to set its data.
        """

        self.players = {None: 0, None: 0, None: 0, None: 0}
        """A dictionary mapping player objects to camera port."""

        # Reference to SCORHE controller
        self.controllerThread, _ = server.masterRunServer(argv)
        """The thread controlling the server.
        
        This allows a way to access all the server settings and configuration. 
        """

        self.serverOptions = self.controllerThread.server.options
        self.clientOptions = self.controllerThread.server.clientOptions

        self.cameras = []
        """A list of the currently known camera ids.
        :type: List[str]
        """

        self.csv = {"maps": [], "labels": []}
        """A deserialized version of the csv specifying experiment data for the researchers."""

        # Reference to main window object items (Main GUI)
        self.buttons = window.buttons
        """A dictionary mapping button names to button objects.
        
        This is used for binding the buttons to listeners to act on button 
        presses.
        """

        self.cameraPickers = window.cameraPickers
        """A dictionary selector names the combobox pickers.
        
        This is used to bind listeners to update the program with user 
        selections.
        """

        self.playersGroup = window.players
        """A dictionary mapping the names of players to their objects.
        
        This is used to ensure videos are streamed to the correct viewport.
        """

        self.text = window.text
        """A dictionary mapping the names of modifiable text fields to their objects.
        
        This allows the program to modify text fields on the program, such as 
        experiment times and the storage indicator.
        """

        self.window = window
        """The main window. Stored for access in the future."""

        # Reference to a update/expUpdater/setter object
        self.updater = updater.Updater(self.camUpdate, self.text,
                                       self.controllerThread,
                                       self.camPorts)

       
        self.time = {'end': datetime.datetime.now(),
                     'start': datetime.datetime.now()}  # type: Dict[str, datetime.datetime]
        """A dictionary holding the start and end time of an experiment."""


        # General info regarding current runtime status
        self.recording = False
        """Whether the program is currently recording from its cameras."""

        self.addedExp = False
        """Whether an experiment had recently been added."""

        self.timed = False
        """Whether the current experiment has a separate thread managing its start and end."""

        self.saveLocation = ""
        """The location where the saved files should be stored in."""


        
        self.endRunThread = None
        """A thread used to end the experiment at the right time."""

        # NC:  The self.startRunThread functionality interferes with the functionality of the self.endRunThread
        self.startRunThread = None
        """A thread used to end the experiment at the right time."""

        self.setter = None
        self.expUpdater = None
       
        self.openSettingsJson()
        # Give server GUI determined settings
        self.setSettings()

        self.window.setSelectionType(self.settings['grouptype'])
        # Sets up buttons
        self.setUpGUIButtons()
        time.sleep(0.1)
        # Declares an instance of the GUI information updater
        # Starts the updater
        self.updater.update()
        # Sets up side info panel
        self.setUpInfoPanel()
        self.camUpdate()
        self.cageUpdate()

    def cageUpdate(self) -> None:
        """Update the cages in the dropdown menus.

        :return: Nothing
        """
        if self.settings['grouptype'].lower() != 'scorhe':
            return
        for name, picker in self.cameraPickers.items():
            prev = self.activeStreams[name]
            if prev and picker.findText(prev) >= 0:
                picker.setCurrentIndex(0)
            picker.clear()
            picker.addItem("")
            picker.addItems(sorted(list(self.settings['camMap']['name'].keys())))
            if prev and picker.findText(prev) >= 0:
                picker.setCurrentIndex(picker.findText(prev))
            else:
                picker.setCurrentIndex(0)

    def camUpdate(self, cameras: Optional[List[str]]=None) -> None:
        """Update the list of cameras if a list was passed.

        This allows calling updateCameras() to simply update the names.
        """
        curCams = set(self.cameras)

        if self.settings['grouptype'].lower() != 'scorhe':
            if cameras is not None:
                inCams = set(cameras)
                deadCams = curCams - inCams
                newCams = inCams - curCams
                self.cameras = cameras

                for cam in deadCams:
                    if cam in self.settings['camMap']['camera']:
                        for selector in self.cameraPickers.values():
                            selector[self.settings['camMap']['camera'][cam]].setEnabled(False)
                    else:  # TODO: log unlabeled cameras in the UI?
                        pass
            else:
                newCams = curCams
                for selector in self.cameraPickers.values():
                    for button in selector.values():
                        button.setEnabled(False)

            for cam in newCams:
                if cam in self.settings['camMap']['camera']:
                    for selector in self.cameraPickers.values():
                        selector[self.settings['camMap']['camera'][cam]].setEnabled(True)
                else:  # TODO: log unlabeled cameras in the UI?
                    pass

        # go through the cameras and get their names, if they have one. otherwise, just use their id
        camNames = [""] + [
            i if i not in self.settings['camMap']['camera'].keys() else
            self.settings['camMap']['camera'][i] for i in self.cameras]
        camNames.sort()

    def setUpGUIButtons(self) -> None:
        """Connect up all main GUI buttons."""
        self.buttons["power"].clicked.connect(self.shutdown)
        self.buttons["start rec"].clicked.connect(self.toggleRecording)
        for pickerName, picker in self.cameraPickers.items():
            if self.settings['grouptype'].lower() == 'scorhe':
                picker.clear()
                picker.addItem("")
                picker.currentIndexChanged.connect(partial(self.setUpPlayers, pickerName))
            else:
                for name, button in picker.items():
                    button.clicked.connect(partial(self.setUpPlayers, pickerName, name))
        self.buttons["settings"].clicked.connect(self.handleSettingsButton)
        self.buttons["add exp"].clicked.connect(self.addExp)
        self.buttons["playback"].clicked.connect(self.launchEditor)
        self.buttons["playback"].setEnabled(False)
        self.buttons["legend"].clicked.connect(self.openLegend)

    def setUpInfoPanel(self) -> None:
        """Instantiate main GUI side info panel."""
        self.text["exp name"].setText("Untitled")
        self.text["start time"].setText("None")
        self.text["end time"].setText("None")
        self.text["time remain"].setText("00:00:00")
        self.text["cam num"].setText("0")

    def setUpPlayers(self, pickerName: str, name: str) -> None:
        """Sets up the players for playing the previews.

        When a group is clicked on in the main window, this function chooses
        which players to start; which players to instantiate and in which frame.
        """
        try:
            isScorhe = self.settings['grouptype'].lower() == 'scorhe'
            if isScorhe:
                name = self.cameraPickers[pickerName].currentText()
            self.stopAllPlayers()
            possPlayers = {0: self.playersGroup["topLeftPlayer"],
                           1: self.playersGroup["topRightPlayer"],
                           2: self.playersGroup["botLeftPlayer"],
                           3: self.playersGroup["botRightPlayer"]}  # type: Dict[int, QtWidgets.QFrame]
            pickers = [self.cameraPickers["topLeftSelect"],
                       self.cameraPickers["topRightSelect"],
                       self.cameraPickers["botLeftSelect"],
                       self.cameraPickers["botRightSelect"]]
            ind = ["topLeftSelect", "topRightSelect", "botLeftSelect",
                   "botRightSelect"]

            def createPlayer(players: Dict[gplayer.GPlayer, QtWidgets.QFrame],
                             winId: sip.voidptr,
                             frame: QtWidgets.QFrame,
                             port: int) -> Dict[gplayer.GPlayer, QtWidgets.QFrame]:
                """Function creates a gstreamer player in provided frame."""
                dim = frame.frameRect()
                player = gplayer.GPlayer(port, winId, dim.width(), dim.height())
                player.setWindowTitle('Player')
                player.start()
                players[player] = frame
                return players

            # Get selected group/groups
            old = self.activeStreams[pickerName]
            self.activeStreams[pickerName] = name

            new = name
            if new:  # things should be disabled
                if old != new:  # this is a new pick, things should be disabled
                    for j in range(0, 4):
                        if ind[j] != pickerName:
                            if isScorhe:
                                pickers[j].model().item(pickers[j].findText(new)).setEnabled(False)
                            else:
                                pickers[j][new].setEnabled(False)
                    if old:  # something else was here, enable it
                        # enable things
                        for j in range(0, 4):
                            if ind[j] != pickerName:
                                if isScorhe:
                                    pickers[j].model().item(pickers[j].findText(old)).setEnabled(True)
                                else:
                                    pickers[j][old].setEnabled(True)
                    else:  # there was nothing else here, no need to enable anything
                        pass
                else:  # there was a stream here, enable for the rest
                    for j in range(0, 4):
                        if ind[j] != pickerName:
                            if isScorhe:
                                pickers[j].model().item(pickers[j].findText(old)).setEnabled(True)
                            else:
                                pickers[j][old].setEnabled(True)
                    self.activeStreams[pickerName] = None
            else:  # no new stream
                if old:  # there was a stream here, enable for the rest
                    for j in range(0, 4):
                        if ind[j] != pickerName:
                            if isScorhe:
                                pickers[j].model().item(pickers[j].findText(old)).setEnabled(True)
                            else:
                                pickers[j][old].setEnabled(True)
                else:  # there wasn't a stream here to begin with, do nothing
                    pass

            cams = []
            # noinspection PyTypeChecker
            for c in self.activeStreams.values():
                if c:
                    if isScorhe:
                        if 'main' in self.settings['camMap']['name'][c]:
                            cams.append(self.settings['camMap']['name'][c]['main'])
                    elif c in self.settings['camMap']['name']:
                        cams.append(self.settings['camMap']['name'][c])
            for camera in cams:
                # For each camera in selected cage issue a individual preview
                # message to each (saves bandwidth then sending to all)
                t1 = threading.Thread(target=self.controllerThread.server.
                                      sendSelectStartPreviewingMessage, args=[camera])
                t1.start()
                t1.join()

            # Update all camera preview ports
            t1 = threading.Thread(target=self.updater.updatePreviewPorts())
            t1.start()
            t1.join()
            cameraToView = []
            for key in ind:
                camera = self.activeStreams[key]
                # Add the selected preview ports to a list
                if camera:
                    if isScorhe:
                        try:
                            camera = self.settings['camMap']['name'][camera]['main']
                        except KeyError:
                            camera = ''
                    else:
                        camera = camera if camera not in self.settings['camMap']['name'].keys() else \
                            self.settings['camMap']['name'][camera]
                if camera and camera in self.camPorts:
                    cameraToView.append(self.camPorts[camera])
                else:
                    cameraToView.append(None)

            # Created all requested players
            for cameraNum in range(0, len(cameraToView)):
                if cameraToView[cameraNum]:
                    self.players = createPlayer(self.players,
                                                possPlayers[cameraNum].winId(),
                                                possPlayers[cameraNum],
                                                cameraToView[cameraNum])

        except Exception as e:
            logger.error(e)
            import traceback
            traceback.print_exception(Exception, e, e.__traceback__)
            traceback.print_tb(e.__traceback__)

    def stopAllPlayers(self) -> None:
        """Function stops all the running players."""
        isScorhe = self.settings['grouptype'].lower() == 'scorhe'
        keys = self.players.keys()
        # noinspection PyTypeChecker
        for player in [key for key in keys if key]:
            player.quit(self.players[player])
        # noinspection PyTypeChecker
        for camera in [c for c in self.activeStreams.values() if c]:
            if isScorhe:
                if 'main' in self.settings['camMap']['name'][camera]:
                    camera = self.settings['camMap']['name'][camera]['main']
            else:
                camera = camera if camera not in self.settings['camMap']['name'].keys() else \
                    self.settings['camMap']['name'][camera]
            if camera and camera in self.camPorts:
                t1 = threading.Thread(target=self.controllerThread.server.
                                      sendSelectStopPreviewingMessage, args=[camera])
                t1.start()
                t1.join()

        t1 = threading.Thread(target=self.updater.updatePreviewPorts())
        t1.start()
        t1.join()
        # Force frame reset
        for key, value in self.playersGroup.items():
            value.setAutoFillBackground(False)
            value.setAutoFillBackground(True)



    def runTimer(self) -> None:
        """Functions schedules start and end time timers for experiment recording."""

        start = "start"
        totalRuntime = (self.time["end"] - self.time["start"]).total_seconds()
        if (totalRuntime > 0):
            self.text["time remain"].setText(str(self.time["end"] - self.time["start"]))
            self.startRecordingAtTime(self.time[start])
            runtimeFromNow = round( (self.time["end"] - datetime.datetime.now()).total_seconds(), 2 )
            self.endRunThread = threading.Timer(runtimeFromNow, self.toggleRecording)
            self.endRunThread.start()
            self.timed = True





# NC: As of 7-7-2020 this function was causing a recording issue and multi-threading errors (see description in attached ERROR_LOG_VideoAPA.txt)
# NC: As such this function is no longer needed for acquisition purposes (this is different for editor purposes please add if you are using for editing purposes please utilize self.recordingStartedMessage() function instead of self.toggleRecording )
    def startRecordingAtTime(self, startTime) -> None:
        """Function starts a timer for experiment recording start time."""
        delay = (startTime - datetime.datetime.now()).total_seconds()

        # self.startRunThread = threading.Timer(delay, self.toggleRecording)  # NC: The timer itself isn't the problem it's the fact the self.toggleRecording is set up to be executed after the timer is done.
        self.startRunThread = threading.Timer(delay, self.recordingStartedMessage(delay)) 
        self.startRunThread.start()

    

    def launchEditor(self) -> None:
        """Launches the editing software."""
        pass



   
    def openSettingsJson(self) -> None:
        """Function attempts to open previous saved settings file and applies to current run."""
        default = {'compression': 1, 'color': True, 'iso': '0', 'len': 2, 'reso': '640x480',
                   'vflip': {'camera': {}, 'default': True}, 'fps': 30,
                   'autogain': True, 'gain': 0,
                   'camMap': {'name': {}, 'camera': {}},
                   'rotation': {'camera': {}, 'default': 0},
                   'zoom location': {'camera': {}, 'default': (0, 0)},
                   'zoom dimension': (1290, 970), #'zoom dimension': (1920, 1080),
                   'pushUpdates': False, 'grouptype': 'SCORHE',
                   'baseDirectory': '', 'active cams': []}
        
        if os.path.isfile(utils.settingsFilePath()):
            with open(utils.settingsFilePath(), 'r') as f:
                data = json.load(f)
                # copies contents of the json in, so any other object with ref
                # to settings will also update
                for c in data:
                    self.settings[c] = data[c]
                # noinspection PyTypeChecker
                for c in default.keys():
                    if c not in self.settings.keys():
                        self.settings[c] = default[c]
                if not isinstance(self.settings['vflip'], dict):
                    self.settings['vflip'] = {'camera': {},
                                              'default': self.settings['vflip']}
                if 'zoom' in self.settings:
                    pts = self.settings['zoom']  # type: Dict[str, Union[List[int], Dict[str, List[int]]]]
                    del self.settings['zoom']
                    pts.items()
                    self.settings['zoom dimension'] = pts['default'][2:]
                    # noinspection PyTypeChecker
                    for cam, window in pts['camera'].items():
                        self.settings['zoom location'][cam] = window[:2]
                        if window[2:] != self.settings['zoom dimension']:
                            logger.warning(
                                    "Warning: {} has dim {}, which was set as {} "
                                    "elsewhere. Check your settings file.".format(
                                            cam, window[2:], self.settings['zoom dimension']))
                            self.settings['zoom dimension'] = window[2:]
        else:
            # If saved settings file does not exist use default
            self.settings = default

    def closeSettingsJson(self) -> None:
        """Save current settings to a file."""
        with open(utils.settingsFilePath(), 'w') as f:
            json.dump(self.settings, f, sort_keys=True, indent=4)

    def saveExpJson(self) -> None:
        """Save current experiment information to a file."""
        if self.addedExp:
            obj = {}
            if os.path.isfile(utils.expFilePath()):
                with open(utils.expFilePath(), 'r') as f:
                    obj = json.load(f)

            name = self.expInfo['name']
            del self.expInfo['name']
            obj[name] = self.expInfo
            with open(utils.expFilePath(), 'w') as f:
                json.dump(obj, f, sort_keys=True, indent=4)
            self.expInfo['name'] = name
            with open(os.path.join(self.expInfo['saveDir'], 'exp.json'), 'w') as f:
                json.dump(self.expInfo, f, sort_keys=True, indent=4)


 
    def toggleRecording(self) -> None:
        """Calls the SCORHE_server's toggle recording function.

        This function is called when the "start recording" button is pressed on
        the GUI, it will also change toggle button text
        """
        
        if self.addedExp:
            self.controllerThread.toggleRecording()
            if not self.recording:
                # Start to record, prompt button to ask for stop recording
                self.buttons["start rec"].setText("Stop Recording")
                self.recording = True
              
            else:
                self.saveExpJson()
                self.addedExp = False
                # Stop recording, prompt button to ask for start recording
                self.buttons["start rec"].setText("Start Recording")
                self.recording = False
                w = self.controllerThread.server.options.captureWidth
                h = self.controllerThread.server.options.captureHeight
                fps = self.controllerThread.server.clientOptions.fps
                f = self.controllerThread.server.options.baseDirectory
                if self.timed:
                    if self.startRunThread is not None and \
                            self.startRunThread.isAlive():
                        self.startRunThread.cancel()
                    if self.endRunThread is not None and \
                            self.endRunThread.isAlive():
                        self.endRunThread.cancel()
                    self.controllerThread.server.options.baseDirectory = ''
                    self.expInfo = {}
                    self.timed = False
                gpac.run(width=w, height=h, fps=fps, filesDir=f)
                self.controllerThread.server.options.activeCams = self.controllerThread.\
                    server.clients.getClients("Camera")
        else:
            if not self.recording:
                # maybe make this less terrible? i.e. let user set recording
                # dir, and everything recorded goes there, instead of setting
                # recording dir per experiment, and leaving default to be in
                # APPDATA_DIR?
                self.controllerThread.server.options.activeCams = self.controllerThread.\
                    server.clients.getClients("Camera")
                baseDir = os.path.join(utils.APPDATA_DIR, "experiments", "Untitled", "")
                if not os.path.exists(baseDir):
                    os.makedirs(baseDir)
                self.controllerThread.server.options.baseDirectory = baseDir
                self.buttons["start rec"].setText("Stop Recording")
                self.recording = True
            else:
                self.buttons["start rec"].setText("Start Recording")
                self.recording = False
                self.controllerThread.server.options.activeCams = self.controllerThread.\
                    server.clients.getClients("Camera")
            self.controllerThread.toggleRecording()


#*************************************************NC ADDED FUNCTION TO TELL USER WHEN THEY HAVE STARTED TO RECORD*************************
    def recordingStartedMessage(self, startTime: float) -> None:
        print("Started Recording at {} with delay of {} seconds.\n".format(datetime.datetime.now(), startTime))

#*****************************************************************************************************************************************

    def handleSettingsButton(self) -> None:
        """Function opens up the settings choice panel and runs setter."""
        self.stopAllPlayers()
        self.setter = cam_set.Setter(self.setSettings,
                                     self.controllerThread,
                                     self.settings, self.camPorts,
                                     self.updater, self.camUpdate,
                                     self.cageUpdate)
        self.setter.runSettings()

    def addExp(self) -> None:
        """Function opens GUI to add experiment and runs exp updater."""
        self.stopAllPlayers()
        if self.recording:
            self.toggleRecording()
        self.expUpdater = exp_updater.ExpUpdater(self)
        self.expUpdater.runExpUpdater()

    def openLegend(self) -> None:
        """
        Look at the CSV and make a legend out of it, attaching cameras to flies
        """
        if not self.csv or 'maps' not in self.csv or 'labels' not in self.csv \
                or not self.csv['maps'] or not self.csv['labels']:
            return
        ui = LegendGui()
        colToNum = {}
        cols = ["A", "B", "C", "D", "E", "F", "G", "H"]
        for a in range(0, len(cols)):
            colToNum[cols[a]] = a
        for obj in self.csv["maps"]:
            if 'WELLID' not in obj or not obj['WELLID']:
                return
            location = obj["WELLID"]
            col = colToNum[location[0]]
            row = int(location[1] + location[2]) - 1
            wid = ui.widgets[row][col]
            wid.setSizePolicy(QtWidgets.QSizePolicy.MinimumExpanding,
                              QtWidgets.QSizePolicy.MinimumExpanding)
            formLayout = QtWidgets.QFormLayout(wid)
            formLayout.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
            count = 0
            for key in self.csv["labels"]:
                if key not in ["WELLID", "WELLNBR", "PLATE"]:
                    label = QtWidgets.QLabel(wid)
                    label.setText(key)
                    formLayout.setWidget(count, QtWidgets.QFormLayout.LabelRole, label)
                    label.setSizePolicy(QtWidgets.QSizePolicy.MinimumExpanding,
                                        QtWidgets.QSizePolicy.MinimumExpanding)
                    value = obj[key]
                    if key != "__rest":
                        # __rest is the key for values without a key, which is an array
                        val = QtWidgets.QLabel(wid)
                        val.setText(value)
                        formLayout.setWidget(count, QtWidgets.QFormLayout.FieldRole, val)
                        val.setSizePolicy(QtWidgets.QSizePolicy.MinimumExpanding,
                                          QtWidgets.QSizePolicy.MinimumExpanding)
                        count = count + 1
                    else:
                        for v in value:
                            val = QtWidgets.QLabel(wid)
                            val.setText(v)
                            formLayout.setWidget(count, QtWidgets.QFormLayout.FieldRole, val)
                            val.setSizePolicy(QtWidgets.QSizePolicy.MinimumExpanding,
                                              QtWidgets.QSizePolicy.MinimumExpanding)
                            count = count + 1
            wid.adjustSize()
        # if the user wants the legend open and still be able to interact, remove modality
        # from legend_gui.py, change exec() to show(), and store the ui somewhere (avoids window
        # closing immediately from gc)
        ui.exec()

    def setSettings(self) -> None:  
        """Function takes provided GUI settings and sets then at the server low level."""
        self.controllerThread.server.options.segmentSize = self.settings['len']
        # clients v0.3 expect this, I think
        # but I don't send this?



        #self.controllerThread.server.options.captureWidth = 1920
        #self.controllerThread.server.options.captureHeight = 1080 


        self.controllerThread.server.options.captureWidth = 1280
        self.controllerThread.server.options.captureHeight = 720



        clientOptions = self.controllerThread.server.clientOptions
        clientOptions.fps = self.settings['fps']
        clientOptions.iso = self.settings['iso']
        clientOptions.colorMode = self.settings['color']
        clientOptions.compression = self.settings['compression']
        clientOptions.autogain = self.settings['autogain']
        clientOptions.rotation = self.settings['rotation']
        clientOptions.zoomLocation = self.settings['zoom location']
        clientOptions.zoomDimension = self.settings['zoom dimension']
       
        clientOptions.vflip = self.settings['vflip'] 
        clientOptions.gain = self.settings['gain']
        clientOptions.camMap = self.settings['camMap']

        self.camUpdate()

    def startLauncher(self, argv: List[str]) -> None:
        """Function starts server and links to the front end logic."""
        self.openSettingsJson()
        # Sets up SCORHE server
        self.controllerThread, _ = server.masterRunServer(argv)
        """:type: SCORHE_server.CameraServerController"""
        # Give server GUI determined settings
        self.setSettings()

        self.window.setSelectionType(self.settings['grouptype'])
        # Sets up buttons
        self.setUpGUIButtons()
        time.sleep(0.1)
        # clientInfo dictionary
        # Declares an instance of the GUI information updater
        self.updater = updater.Updater(self.camUpdate, self.text,
                                       self.controllerThread,
                                       self.camPorts)
        # Starts the updater
        self.updater.update()
        # Sets up side info panel
        self.setUpInfoPanel()
        self.camUpdate()
        self.cageUpdate()

    def shutdown(self, *_) -> None:
        """Shuts down launcher."""
        # Stop the GUI info updates
        w = self.controllerThread.server.options.captureWidth
        h = self.controllerThread.server.options.captureHeight
        fps = self.controllerThread.server.clientOptions.fps
        f = self.controllerThread.server.options.baseDirectory
        if self.timed:
            if self.startRunThread is not None and self.startRunThread.isAlive():
                self.startRunThread.cancel()
            if self.endRunThread is not None and self.endRunThread.isAlive():
                self.endRunThread.cancel()
            if self.recording:
                self.toggleRecording()
        self.updater.stop()
        # Save all camera client information
        self.closeSettingsJson()
        self.saveExpJson()
        # Restarts the clients
        self.controllerThread.reboot()
        # Shutdown server
        self.controllerThread.close()
        gpac.run(width=w, height=h, fps=fps, filesDir=f)
        sys.exit()


def main(argv: List[str]) -> None:
    """
    Main function initiates the launch object and main window GUI and runs them
    """
    app = QtWidgets.QApplication(argv)
    window = AcquisitionWindow()
    launch = LaunchObject(argv, window)
    #launch.startLauncher(argv)  # NC RECOMMENT
    window.closeEvent = launch.shutdown
    #window.showFullScreen()
    window.showNormal()
    #window.showMinimized()  
    sys.exit(app.exec_())
    

if __name__ == '__main__':
    main(sys.argv[1:])
