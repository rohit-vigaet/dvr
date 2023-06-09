"""
Server main controller exists within this file. This file can be run bare-bones
command line or be started automatically through the server launcher. 
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
from collections import defaultdict
import ipaddress
import logging
import os
import platform
import queue
import re
import socket
import socketserver
import struct
import sys
import threading
import time
from typing import DefaultDict, Tuple, Callable, Optional, Any, Iterable, \
    Dict, List, Union

from scorhe_server import gpac, protocol, server_protocols
import utils

if platform.system() == 'Linux':
    import fcntl

logger = logging.getLogger(__name__)

NAME = 'SCORHE_server'
VERSION = '1.0.1'
CLIENT_VERSION = None
CLIENT_FOLDER = './client'


def printHelp() -> None:
    """
    A function that prints the different parameters this file takes when run
    directly from the commandline.

    TODO: Either remove or replace with actual commandline parser.

    :return: Nothing
    """
    print('SCORHE server')
    print('Use the following arguments:')
    print('\t-d [directory]            (set the directory to record videos into)')
    print('\t-f [h264|mp4]             (set the file format to stream)')
    print('\t--push [true|false|t|f]   (push current client version to all connected cameras)')
    print('\thelp                      (display this help)')


class ClientOptions:
    """Object to store settings so IDE is more helpful when using settings.
    Also allows for listeners for settings if necessary.

    These are settings that will be sent to the clients.
    """
    __slots__ = ('_camMap', '_rotation', '_zoomLocation', '_fps', '_iso',
                 '_colorMode', '_compression', '_autogain', '_vflip', '_gain',
                 '_brightness', '_sendToSelect', '_sendToAll', '_zoomDimension',
                 )

    def __init__(self,
                 sendToSelect: Callable[[str, str, str], Any],
                 sendToAll: Callable[[str, str], Any],
                 camMap: Optional[Dict[str, str]]=None,
                 rotation: Optional[DefaultDict[str, int]]=None,
                 zoomLocation: Optional[DefaultDict[str, Tuple[int, int]]]=None,
                 fps: int=30,
                 iso: int=0,
                 colorMode: bool=False,
                 compression: float=1,
                 autogain: bool=True,
                 vflip: Optional[DefaultDict[str, bool]]=None,
                 gain: float=0,
                 brightness: int=50,
                 zoomDimension: Tuple[int, int]=(1296, 972), 

                 
                 ):
        """Sets the settings for all cameras that are connected.

        Keep in mind that this doesnt actually send the settings to all cameras.
        To send the settings, use ``forcePush``.

        :param sendToSelect: The function used to send the values set here to
            select cameras.
        :param sendToAll: the function used to send the values set here to all
            cameras.
        :param camMap: A mapping between camera ids and their names.
        :param rotation: A mapping between camera ids and their rotation.
        :param zoomLocation: A mapping between camera ids and their zoom window.
        :param fps: The fps for all connected cameras
        :param iso: The ISO (sensitivity to light) for all connected cameras.
        :param colorMode: Whether all connected cameras should record in color
            or not.
        :param compression: The factor by which to compress the sides of the
            image for all cameras.
        :param autogain: Whether to enable autogain for all cameras.
        :param vflip: A mapping between camera id and whether they should be
            flipped vertically.
        :param gain: The gain for all cameras.
        :param brightness: The brightness for all cameras.
        :param zoomDimension: The size of the zoom window.
        """
        self._sendToSelect = sendToSelect
        self._sendToAll = sendToAll
        self._camMap = {} if camMap is None else camMap
        self._rotation = defaultdict(lambda: 0) if rotation is None else rotation  # type: DefaultDict[str, int]
        self._zoomLocation = defaultdict(lambda: (0, 0)) if \
            zoomLocation is None else zoomLocation  # type: DefaultDict[str, Tuple[int, int]]
        self._vflip = defaultdict(lambda: False) if vflip is None else vflip  # type: DefaultDict[str, bool]
        self._fps = fps
        self._iso = iso
        self._colorMode = colorMode
        self._compression = compression
        self._autogain = autogain
        self._gain = gain
        self._brightness = brightness
        self._zoomDimension = zoomDimension

    def forcePush(self, cams: Optional[Iterable[str]]=None) -> None:
        """Pushes the current settings to all connected cameras.

        Keep in mind that, in general, setting any item explicitly updates the
        cameras. Use this only when you have to send everything.

        :param cams: What cameras to send the message to, or ``None`` to send
            to all the cameras
        :return: Nothing
        """
        if cams is None:
            self._sendToAll('Camera', 'set camMap')
            self._sendToAll('Camera', 'set rotation')
            self._sendToAll('Camera', 'set zoom points')
            self._sendToAll('Camera', 'set vflip')
            self._sendToAll('Camera', 'set FPS')
            self._sendToAll('Camera', 'set ISO')
            self._sendToAll('Camera', 'set color mode')
            self._sendToAll('Camera', 'set compression')
            self._sendToAll('Camera', 'set autogain')
            self._sendToAll('Camera', 'gain')
            self._sendToAll('Camera', 'set brightness')
        else:
            for cam in cams:
                self._sendToSelect('Camera', 'set camMap', cam)
                self._sendToSelect('Camera', 'set rotation', cam)
                self._sendToSelect('Camera', 'set zoom points', cam)
                self._sendToSelect('Camera', 'set vflip', cam)
                self._sendToSelect('Camera', 'set FPS', cam)
                self._sendToSelect('Camera', 'set ISO', cam)
                self._sendToSelect('Camera', 'set color mode', cam)
                self._sendToSelect('Camera', 'set compression', cam)
                self._sendToSelect('Camera', 'set autogain', cam)
                self._sendToSelect('Camera', 'gain', cam)
                self._sendToSelect('Camera', 'set brightness', cam)

    def _updateDefaultdict(self,
                           key: str,
                           old: DefaultDict[str, Any],
                           new: DefaultDict[str, Any],
                           ) -> None:
        """Sends updates to all cameras that changed value between old and new.

        The setting that changed and is being set is defined by ``key``.

        :param key: What setting changed.
        :param old: The old defaultdict setting values for the cameras.
        :param new: The new defaultdict setting values for the cameras.
        :return: Nothing
        """
        keys = set(new.keys()) | set(old.keys())
        for k in keys:
            if old[k] != new[k]:
                self._sendToSelect('Camera', 'set ' + key, k)

    # region Properties of the client settings
    @property
    def camMap(self) -> Dict[str, str]:
        """A dictionary mapping the IDs of clients to their names.

        A missing camera ID means that its name had not been set, and therefore
        the name that should be shown is the camera ID itself.

        Setting this value (but no updating individual mappings) will send a
        message to all cameras whose name been added, changed or removed to
        update their own name.

        :return: A dictionary mapping camera IDs to their names.
        """
        return self._camMap

    @camMap.setter
    def camMap(self, value: Dict[str, Dict[str, str]]) -> None:
        old = self._camMap
        self._camMap = value['camera']
        camKeys = set(value.keys()) | set(old.keys())
        for cam in camKeys:
            if cam not in old or cam not in value or old[cam] != value[cam]:
                self._sendToSelect('Camera', 'set camMap', cam)

    @property
    def rotation(self) -> Dict[str, int]:
        """A defaultdict mapping the IDs of the clients to their rotation.

        A missing camera ID mean that its rotation is the default value of the
        defaultdict (``0`` by default).

        Setting this value (but not updating individual mappings) will send a
        message to all cameras whose rotation has been added, changed or
        removed to update their own rotation.

        To set the value, pass a regular dict with the default value set under
        the key ``default`` and the actual mapping under ``camera``.

        Rotations are all multiples of 90. Values under 0 and above 360 are
        allowed.

        :return: A defaultdict mapping camera IDs to their names, and
            specifying the default rotation.
        """
        return self._rotation

    @rotation.setter
    def rotation(self, value: Dict[str, Union[int, Dict[str, int]]]) -> None:
        old = self._rotation  # type: DefaultDict[str, int]
        t = defaultdict(lambda: value['default'])  # type: DefaultDict[str, int]
        t.update(value['camera'])
        self._rotation = t
        self._updateDefaultdict('rotation', old, t)

    @property
    def zoomLocation(self) -> Dict[str, Tuple[int, int]]:
        """A defaultdict mapping the IDs of clients to the location of their zoom window.

        A missing camera ID means that its zoom window is the default value of
        the defaultdict (``(0, 0)`` by default).

        Setting this value (but not updating individual mappings) will send a
        message to all cameras whose zoom window has been added, changed, or
        removed to update their own zoom window.

        To set the value, pass a regular dict with the default value set under
        the key ``default`` and the actual mapping under ``camera``.

        A zoom window/zoom points is a 2-tuple of int which represents the x
        and y coordinates of the top-left corner of the window.

        :return: A defaultdict mapping the IDs of clients to their zoom window,
            and specifying the default zoom window.
        """
        return self._zoomLocation

    @zoomLocation.setter
    def zoomLocation(self, value: Dict[str, Union[Tuple[int, int], Dict[str, Tuple[int, int]]]]) -> None:
        old = self._zoomLocation  # type: DefaultDict[str, Tuple[int, int]]
        t = defaultdict(lambda: value['default'])  # type: DefaultDict[str, Tuple[int, int]]
        t.update(value['camera'])
        self._zoomLocation = t
        self._updateDefaultdict('zoom points', old, t)

    @property
    def vflip(self) -> Dict[str, bool]:
        """A default dict mapping the IDs of clients to their vflip value.

        A missing camera ID means that its zoom window the default value of
        the defaultdict (``False`` by default).

        Setting this value (but not updating individual mappings) will send a
        message to all cameras whose vflip value has been added, changed or
        removed to update their own vflip value.

        To set the value, pass a regular dict with the default value set under
        the key ``default`` and the actual mapping under ``camera``.

        Vflip refers to whether the camera's view should be flipped vertically
        or not. A value of ``True`` means it should be flipped, and ``False``
        means it should not.

        :return: A defaultdict mapping the IDs of clients to their vflip value,
            and specifying the default vflip value.
        """
        return self._vflip

    @vflip.setter
    def vflip(self, value: Dict[str, Union[bool, Dict[str, bool]]]) -> None:  # *****************NC: TypeError thrown here ********************************************************************************************************************
        old = self._vflip  # type: DefaultDict[str, bool]
        t = defaultdict(lambda: value['default'])   # type: DefaultDict[str, bool]


      
        t.update(value['camera'])    # *************************************** NC:  TYPE ERROR THROWN BY THIS ***********************************************************************************************************************************************************
        
        self._vflip = t
        self._updateDefaultdict('vflip', old, t)

    @property
    def fps(self) -> int:
        """The fps for all cameras connected to this server.

        When this value is set directly, a message is sent to all cameras to
        set their fps, which should take effect in the next call to record or
        preview.

        :return: The fps for all cameras connected to this server.
        """
        return self._fps

    @fps.setter
    def fps(self, value: int) -> None:
        self._fps = value
        self._sendToAll('Camera', 'set FPS')

    @property
    def iso(self) -> int:
        """The ISO for all cameras connected to this server.

        Setting this value send a message to all cameras to set their ISO. As
        per the picamera documentation, this value represents how sensitive the
        camera is to light, where a higher value is more sensitive. 0 is auto.

        :return: The ISO for all cameras connected to this server
        """
        return self._iso

    @iso.setter
    def iso(self, value: int) -> None:
        self._iso = value
        self._sendToAll('Camera', 'set ISO')

    @property
    def colorMode(self) -> bool:
        """Whether the cameras are recording in color or grayscale.

        This property specifies whether to record in color (``True``) or in
        grayscale (``False``).

        Setting this value sends a message to all the connected cameras to set
        their values.

        :return: Whether the cameras are recording in color or grayscale.
        """
        return self._colorMode

    @colorMode.setter
    def colorMode(self, value: bool) -> None:
        self._colorMode = value
        self._sendToAll('Camera', 'set color mode')

    @property
    def compression(self) -> float:
        """Sets the factor with which to reduce the sides of the image.

        Setting this value sends a message to all cameras to set their
        compression.

        Note that since this modifies how the `sides` of the image are
        compressed, the entire frame is compressed by a factor of
        ``compression`` squared.

        :return: The factor with which to reduce the sides of the image.
        """
        return self._compression

    @compression.setter
    def compression(self, value: float) -> None:
        self._compression = value
        self._sendToAll('Camera', 'set compression')

    @property
    def autogain(self) -> bool:
        """Enables or disables the autogain of the cameras.

        If this property is ``False`` autogain is disabled. If this property is
        ``True``, autogain is enabled.

        Setting this value sends a message to all connected cameras to set
        their autogain.

        :return: Whether autogain is enabled for the cameras.
        """
        return self._autogain

    @autogain.setter
    def autogain(self, value: bool) -> None:
        self._autogain = value
        self._sendToAll('Camera', 'set autogain')

    @property
    def gain(self) -> float:
        """Sets the gain for all the cameras connected to this server.

        Setting this value sends a message to all connected cameras to set
        their gain.

        :return: The gain of all cameras connected to this server.
        """
        return self._gain

    @gain.setter
    def gain(self, value: float) -> None:
        self._gain = value
        self._sendToAll('Camera', 'set gain')

    @property
    def brightness(self) -> int:
        """Sets the brightness of the cameras connected to the server.

        Setting this value sends a message to all connected cameras to set
        their brightness.

        :return: The brightness of the cameras connected to the server.
        """
        return self._brightness

    @brightness.setter
    def brightness(self, value: int) -> None:
        self._brightness = value
        self._sendToAll('Camera', 'set brightness')

    @property
    def zoomDimension(self) -> Tuple[int, int]:
        """Sets the dimension of the camera view for all clients.

        Setting this value sends a message to all connected cameras to set
        their zoom dimension.

        The last 2-tuple of ints represents the zoom window's width and height
        in pixels. The pis get stuck when set to a viewport with an extreme
        aspect ratio, so the protocol rejects viewport with an aspect ratio
        that is not within 0.5 and 2.

        :return: The dimension of the zoom window of the clients.
        """
        return self._zoomDimension

    @zoomDimension.setter
    def zoomDimension(self, value: Tuple[int, int]) -> None:
        self._zoomDimension = value
        self._sendToAll('Camera', 'set zoom points')
    # endregion


class ServerOptions:
    """Object to store settings so IDE is more helpful when using settings.
    Also allows for listeners for settings if necessary.

    These are settings that will not be sent to the clients.
    """
    __slots__ = ('segmentSize', 'captureWidth', 'captureHeight',
                 'baseDirectory', 'format', 'clientFolder', 'clientVersion',
                 'pushUpdates', 'activeCams',
                 )

    def __init__(self,
                 segmentSize: int=2,
                 captureWidth: int=640,
                 captureHeight: int=480,
                 baseDirectory: str='',
                 videoFormat: str='h264',
                 clientFolder: str='./client',
                 clientVersion: str='0.0.0',
                 pushUpdates: bool=True,
                 activeCams: Optional[Iterable[str]]=None
                 ):
        """

        :param segmentSize: The number of minutes in each segment, as an int.
        :param captureWidth: The width of the video capture. Used for
            conversion of the videos.
        :param captureHeight: The height of the video capture. Used for
            conversion of the videos.
        :param baseDirectory: The location to store the experiments in.
        :param videoFormat: The format of the videos. Currently ignored and
            h264 remains the default for the cameras.
        :param clientFolder: The folder where the current code for the clients
            are at.
        :param clientVersion: The version the current clients are on.
        :param pushUpdates: Whether to push updates to the clients.
        :param activeCams: A list of camera IDs that are to be counted as
            active, that is to tell when to start and stop recording.
        """
        self.segmentSize = segmentSize
        self.captureWidth = captureWidth  # type: int
        self.captureHeight = captureHeight  # type: int
        self.baseDirectory = baseDirectory  # type: str
        self.format = videoFormat  # type: str
        self.clientFolder = clientFolder  # type: str
        self.clientVersion = clientVersion  # type: str
        self.pushUpdates = pushUpdates  # type: int
        self.activeCams = [] if activeCams is None else activeCams
        """:type activeCams: Iterable[str]"""


def parseArgv(argv: List[str]) -> ServerOptions:
    """
    Initializes the options and parses the command line options. If there is an
    error in the command line options, the help-text is printed, and after user
    input, the program is exited.

    TODO: Switch to using this to parse the settings json rather than in acquisition

    :param argv: A list of the commandline options passed to this program.
    :return: An object representing the the options for the server.
    """
    options = ServerOptions()
    try:
        while argv:
            arg = argv.pop(0)
            if arg == '-d':
                options.baseDirectory = argv.pop(0)
            elif arg == '-f':
                options.format = argv.pop(0)
            elif arg == '--push':
                arg = argv.pop(0)
                if arg == 'true' or arg == 't':
                    options.pushUpdates = True
                elif arg == 'false' or arg == 'f':
                    options.pushUpdates = False
                else:
                    raise Exception()
        if options.clientFolder and os.path.isdir(options.clientFolder):
            files = os.listdir(os.path.join(options.clientFolder, 'source'))
            files = set([os.path.basename(p) for p in files])
            expected = {'protocol.py', 'client.py',
                        'screen.py', '__main__.py'}
            if not expected.issubset(files):
                options.pushUpdates = False
                return options
            with open(os.path.join(options.clientFolder, 'source', 'client.py'), 'r') as f:
                eqs = ['=', ' =', '= ', ' = ']
                regexps = [re.compile('(?<=VERSION{}[\'"])[a-zA-Z0-9_.]+(?=[\'"]\\s*)'.format(eq)) for eq in eqs]
                # noinspection PyTypeChecker
                for line in f:
                    for regex in regexps:
                        options.clientVersion = regex.search(line)
                        if options.clientVersion is not None:
                            options.clientVersion = options.clientVersion.group()
                            break
                    if options.clientVersion is not None:
                        break
        else:
            options.pushUpdates = False
    except (Exception, IndexError, IOError) as e:
        logger.exception(e)
        printHelp()
        input()
        exit(1)
    return options


class RecordingOrStreamException(Exception):
    """Exception used for identifying a problem in streaming video."""
    pass


class ServerThread(threading.Thread):
    """Runs the actual server object.

    This is kept on a separate thread to protect against errors.
    """

    def __init__(self, server):
        threading.Thread.__init__(self)
        self.server = server

    def run(self) -> None:
        """
        Serve until an explicit shutdown is called by the controller.

        :return: Nothing
        """
        logger.info('Starting server...')
        self.server.serve_forever()
        logger.info('Server shut down')


class CameraServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """A TCP server that keeps track of SCORHE clients and applications.

    A number of event callbacks are provided to invoke common operations,
    like telling cameras to record or notify the applications that a file is
    finished downloading.
    """

    def __init__(self, port, controller, serverOptions):

        # Start TCP server on predetermined port
        socketserver.TCPServer.__init__(self, ('', port),
                                        ClientRequestHandler)
        logger.debug('Port: {}'.format(port))
        self.daemon_threads = True
        # Reference to clients
        self.clients = ClientConnections()
        # Reference to server controller
        self.controller = controller
        # Reference to command line options (if needed)
        self.options = serverOptions  # type: ServerOptions
        self.clientOptions = ClientOptions(self.sendToSelect, self.sendToAll)  # type: ClientOptions
        self.expName = None
        self.startTime = None
        self.endTime = None
        self.camNum = None
        # General recording info
        self.recording = False
        self.previewing = False
        self.cameraSettingsSet = False
        self.clientVersion = CLIENT_VERSION
        self.clientFolder = CLIENT_FOLDER

    def sendToAll(self, clientType: str, messageID: str, *args) -> None:
        """Sends a message to all clients of the given type.

        :param clientType: The type of the client to send to (Unregistered or
            Camera)
        :param messageID: The id of the message (i.e. the key that is the index
            for the handler that should be called).
        :return: Nothing
        """
        self.clients.sendToAll(self, clientType, messageID, *args)

    def sendToSelect(self, clientType: str, messageID: str, cameraID: str, *args) -> None:
        """Sends a message to a select client of the given type and ID.

        :param clientType: The type of the client to send to (Unregistered or
            Camera)
        :param messageID: The id of the message (i.e. the key that is the index
            for the handler that should be called).
        :param cameraID: The id of the camera to send the message to.
        :return: Nothing
        """
        self.clients.sendToSelect(self, clientType, messageID, cameraID, *args)

    def sendToSelects(self, clientType: str, messageID: str, cameraIDs: Iterable[str], *args) -> None:
        """Sends a message to select clients of a given type and of each of the
        IDs.

        :param clientType: The type of the client to send to (Unregistered or
            Camera)
        :param messageID: The id of the message (i.e. the key that is the index
            for the handler that should be called).
        :param cameraIDs: A list of ids for the cameras to send the message to.
        :return: Nothing
        """
        self.clients.sendToSelects(self, clientType, messageID, cameraIDs, *args)

    def sendExpInfoMessages(self) -> None:
        """Sends a message to all cameras with the experiment information."""
        logger.info('Send Exp Info')
        self.sendToAll('Camera', 'send exp')

    def sendStartRecordingMessages(self) -> None:
        """Tells cameras to start recording."""
        if not self.cameraSettingsSet:
            self.sendSetSettingsMessages()
            self.cameraSettingsSet = True
        if self.recording:
            raise RecordingOrStreamException(
                    'Cannot start recording when already recording')
        self.recording = True
        logger.info('Start recording')
        

        self.sendToSelects('Camera', 'start recording', self.options.activeCams,
                           time.strftime('%Y-%m-%d %Hh%Mm%Ss'))

    def sendSplitRecordingMessages(self) -> None:
        """Tells cameras to continue to record, but into a new file."""
        if not self.recording:
            raise RecordingOrStreamException(
                    'Cannot split recording when not recording')
        logger.info('Split recording')
        self.sendToSelects('Camera', 'start recording', self.options.activeCams,
                           time.strftime('%Y-%m-%d %Hh%Mm%Ss'))

    def sendStopRecordingMessages(self) -> None:
        """Tells cameras to stop recording."""
        if not self.recording:
            raise RecordingOrStreamException(
                    'Cannot stop recording when not recording')
        self.recording = False
        logger.info('Stop recording')
        self.sendToAll('Camera', 'stop recording')

    def sendStartPreviewingMessages(self) -> None:
        """Tells cameras to start previewing."""
        if not self.cameraSettingsSet:
            self.sendSetSettingsMessages()
            self.cameraSettingsSet = True
        if self.previewing:
            raise RecordingOrStreamException(
                    'Cannot start previewing when already previewing')
        self.previewing = True
        logger.info('Start Previewing')
        self.sendToAll('Camera', 'start previewing')

    def sendStopPreviewingMessages(self) -> None:
        """Tells cameras to stop previewing."""
      
        if not self.previewing:     # ********************* NC: THIS exception is being thrown 6-25-20                                            **************************************************
            raise RecordingOrStreamException('Cannot stop previewing when not previewing')


        self.previewing = False
        logger.info('Stop Previewing')
        self.sendToAll('Camera', 'stop previewing')

    def sendSelectStartPreviewingMessage(self, cameraID: str) -> None:
        """Tells one camera that is provided to start previewing.

        :param cameraID: The id of the camera that should start previewing.
        :return: Nothing
        """
        if not self.cameraSettingsSet:
            self.sendSetSettingsMessages()
            self.cameraSettingsSet = True
        self.sendToSelect('Camera', 'start previewing', cameraID)
        logger.info('Started Previewing ' + str(cameraID))

    def sendSelectStopPreviewingMessage(self, cameraID: str) -> None:
        """Tells the one camera that is provided to stop previewing.

        :param cameraID: The id of the camera that should stop previewing.
        :return: Nothing
        """
        self.sendToSelect('Camera', 'stop previewing', cameraID)
        logger.info('Stopped Previewing ' + str(cameraID))

    def sendSetSettingsMessages(self) -> None:
        """Sets all video viewing settings"""
        self.sendToAll('Camera', 'sync clocks')
        self.sendToAll('Camera', 'set FPS')
        self.sendToAll('Camera', 'set ISO')


        self.sendToAll('Camera', 'set dimension')   #  ******************************************************************************************************************************************************&&&&&&&&&&&&&&&
        
        self.sendToAll('Camera', 'set stream format')
        self.sendToAll('Camera', 'set autogain')
        self.sendToAll('Camera', 'set zoom points')
        self.sendToAll('Camera', 'set color mode')
        self.sendToAll('Camera', 'set compression')
        for cam in self.clientOptions.camMap:
            self.sendToSelect('Camera', 'set camMap', cam)
        for cam in self.clientOptions.rotation:
            self.sendToSelect('Camera', 'set rotation', cam)
        # self.sendToAll('Camera', 'set gain')
        logger.info('Set settings')

    def sendRebootMessage(self) -> None:
        """Tells whole system to reboot"""
        self.sendToAll('Camera', 'reboot')

    def sendRestartMessage(self) -> None:
        """Tells software to restart"""
        self.sendToAll('Camera', 'restart')

    def sendSetCageName(self) -> None:
        """Sets the cages of the cameras"""
        for cam in self.clientOptions.camMap:
            self.sendToSelect('Camera', 'set camMap', cam)

    def sendSetView(self) -> None:
        """Sets the views of the cameras"""
        self.sendToAll('Camera', 'set view')

    def sendSyncClocks(self) -> None:
        """Syncs system time with clients"""
        self.sendToAll('Camera', 'sync clocks')

    @staticmethod
    def error(client: 'ClientController', message: str) -> None:
        """Prints an error message to the console.

        :param client: The client that sent the error message.
        :param message: The error message sent by the client.
        :return: Nothing
        """
        logger.error('{}: {}'.format(client.socket.getpeername(), message))

    @staticmethod
    def downloadFinished(filename: str, numFrames: int, _timestamp: str) -> None:
        """Tells applications that a video has finished downloading.

        :param filename: The file where the download finished.
        :param numFrames: The number of frames in the file.
        :param _timestamp: The timestamp the download finished. Unused.
        :return: Nothing
        """
        logger.info('Finished {}: {} frames'.format(
                utils.truncateFilename(filename), numFrames))

    def storeData(self, client: 'CameraClient', datatype: str, data: float) -> None:
        """Stores data from the client.

        :param client: The client the data came from.
        :param datatype: What kind of data is passed.
        :param data: The data being passed from the client.
        :return: Nothing
        """
        name = client.cameraID
        try:
            name = "{} {}".format(self.clientOptions.camMap[name], name)
        except KeyError:
            pass
        ln = "{} [{}]: {} = {}".format(time.strftime('%Y-%m-%d %H:%M:%S'), name,
                                       datatype, data)
        with open(os.path.join(self.options.baseDirectory, 'data.log'), 'a') as f:
            print(ln, file=f)


class CameraServerController(threading.Thread):
    """Controller for the SCORHE server application.

    Provides a number of controls associated with user actions.

    This is literally a queue wrapper for the user input.

    This thread can be bypassed by calling the serverThread directly (not
    threadsafe).
    """

    __slots__ = ('server', 'splitScheduler', 'recordStartTime', 'asyncQueue')

    def __init__(self, serverOptions):
        threading.Thread.__init__(self)
        # Reference to the server thread
        self.server = CameraServer(24461, self, serverOptions)  # type: CameraServer
        # Scheduler for splitting recordings (default is 120 seconds)
        self.splitScheduler = None
        # Variable to sync recordings
        self.recordStartTime = None
        # Reference to the asynchronous queue to run functions, well, asynchronously
        self.asyncQueue = protocol.AsyncFunctionQueue()

    def run(self) -> None:
        """Run a protocol using a thread-safe queue to register events."""
        self.asyncQueue.start()
        logger.info('Controller shut down')

    def startRecording(self) -> None:
        """Invoke this to have the cameras start recording."""
        try:
            self.recordStartTime = time.time() + 1
            self.asyncQueue.call(self.server.sendStartRecordingMessages)
            self.splitScheduler = threading.Timer(
                    self.server.options.segmentSize*60 , self.splitRecording)
            self.splitScheduler.start()
        except RecordingOrStreamException as err:
            logger.error(err)

    def splitRecording(self) -> None:
        """Called periodically to make the cameras record into a new file."""
        try:
            self.recordStartTime = time.time()
            self.asyncQueue.call(self.server.sendSplitRecordingMessages)
            self.splitScheduler = threading.Timer(
                    self.server.options.segmentSize*60, self.splitRecording)
            self.splitScheduler.start()
        except RecordingOrStreamException as err:
            logger.error(err)

    def stopRecording(self) -> None:
        """Invoke this to have the cameras stop recording."""
        try:
            self.asyncQueue.call(self.server.sendStopRecordingMessages)
            self.splitScheduler.cancel()
        except RecordingOrStreamException as err:
            logger.error(err)

    def toggleRecording(self) -> None:
        """Invoke this to have the cameras switch between recording and not."""
        if self.server.recording:
            self.stopRecording()
        else:
            self.startRecording()

    def startPreviewing(self) -> None:
        """Invoke this to have the cameras start previewing."""
        try:
            self.asyncQueue.call(self.server.sendStartPreviewingMessages)
        except RecordingOrStreamException as err:
            logger.error(err)

    def stopPreviewing(self) -> None:
        """Invoke this to have the cameras stop previewing."""
        try:
            self.asyncQueue.call(self.server.sendStopPreviewingMessages)
        except RecordingOrStreamException as err:
            logger.error(err)

    def togglePreviewing(self) -> None:
        """Invoke this to have the cameras switch between previewing and not."""
        if self.server.previewing:
            self.stopPreviewing()
        else:
            self.startPreviewing()

    def reboot(self) -> None:
        """Sends a message to reboot al the cameras."""
        self.asyncQueue.call(self.server.sendRebootMessage)

    def restart(self) -> None:
        """Sends a message to restart al the cameras."""
        self.asyncQueue.call(self.server.sendRestartMessage)

    def close(self) -> None:
        """Gracefully shut down the server."""
        if self.server.recording:
            self.stopRecording()
        if self.server.previewing:
            self.stopPreviewing()
        self.asyncQueue.finish()
        self.server.shutdown()


class ClientRequestHandler(socketserver.StreamRequestHandler):
    """Handler class that keeps a connection between a client and the server.

    Handle is called once per object, and attempts to register the client.
    """

    def handle(self) -> None:
        """Handles a new connection.

        The client starts out as an UnregisteredClient, but then becomes a
        CameraClient or an ApplicationClient when a valid handshake is
        received.

        :return: Nothing
        """
        logger.debug('Server socket connection: {}'.format(self.request))
        client = self.server.clients.getClient(self.request)
        if not client:
            client = self.server.clients.register(self.server,
                                                  self.request, 'Unregistered')
        try:
            while True:
                incomingMessage = self.request.recv(1024)
                if not incomingMessage:
                    logger.debug('No incoming message, exiting {}'.format(self.request.getpeername()))
                    return
                client = self.server.clients.getClient(self.request)
                client.handle(self.server, incomingMessage)
        except ConnectionResetError:
            logger.warning('{}: connection closed'.format(
                    client.socket.getsockname()[0]))
            self.server.clients.unregister(self.request,
                                           client.clientType)
        finally:
            self.request.close()


class ClientConnections:
    """A container object for all clients."""
    unregisteredProtocol = server_protocols.UnregisteredProtocol()
    cameraProtocol = server_protocols.CameraProtocol()

    def __init__(self):
        # Dictionary to keep track of client types
        self.clients = {'Unregistered': {},
                        'Camera': {}}  # type: dict[str: dict[str: ClientController]]
        # Dictionary to keep track of different protocols to be used
        self.protocols = {'Unregistered': ClientConnections.unregisteredProtocol,
                          'Camera': ClientConnections.cameraProtocol}

    def register(self,
                 server: CameraServer,
                 sock: socket.socket,
                 clientType: str,
                 *args) -> 'ClientController':
        """Registers the given socket as a client of the given type.

        Prevent a potential DDOS attack that sends multiple handshakes by
        first checking that a client object isn't already registered.

        :param server: The server to register the client with.
        :param sock: The socket connecting to the client.
        :param clientType: The type of client being registered (Unregistered or
            Camera), being where it should be looked for in the future.
        :return: The client that got registered.
        """
        if sock not in self.clients[clientType].keys():
            self.clients[clientType][sock] = makeClient(
                    server, sock, clientType, self.protocols[clientType], *args)
        return self.clients[clientType][sock]

    def unregister(self, sock: socket.socket, clientType: str) -> None:
        """Unregisters the socket as the given client type.

        :param sock: The socket of the client to remove.
        :param clientType: The type of the client to remove (Unregistered or
            Camera)
        :return Nothing
        """
        try:
            del self.clients[clientType][sock]
        except KeyError:
            logger.debug(self.clients)
            logger.debug(clientType)
            logger.debug(sock)
            pass

    def getClient(self, sock: socket.socket) -> Optional['ClientController']:
        """Returns a handle to the client with the given socket.

        If the socket has connected before, find it in the list of registered
        clients and return it.

        :param sock: The socket belonging to the client that is being looked up.
        :return: The client with the given socket, or None if the client cannot
            be found.
        """
        # noinspection PyTypeChecker
        for clients in self.clients.values():
            if sock in clients:
                return clients[sock]
        # Return None if the socket is not registered in any category
        return None

    def getClients(self, clientType: str) -> Iterable['ClientController']:
        """Returns a list of all clients of the given type.

        :param clientType: The type of client (Unregistered or Camera)
        :return: A list of all the clients of a given type.
        """
        return self.clients[clientType].values()

    def sendToAll(self,
                  server: CameraServer,
                  clientType: str,
                  messageID: str,
                  *args) -> None:
        """Send a message to all clients of the given type.

        :param server: The server object handling the clients.
        :param clientType: The type of the clients (Unregistered or Camera)
        :param messageID: The id of the message, i.e. the key for the protocol
            rule to run.
        :return: Nothing
        """
        # noinspection PyTypeChecker
        for client in self.clients[clientType].values():
            client.send(server, messageID, *args)
            if messageID == "stop previewing" and client.previewSocket is not None:
                client.previewSocket.close()

    def sendToSelect(self,
                     server: CameraServer,
                     clientType: str,
                     messageID: str,
                     cameraID: str,
                     *args) -> None:
        """Sends a message to a client with a specific type and id.

        Simply calls ``sendToSelects`` with a list of a single camera id.

        :param server: The server object handling the clients.
        :param clientType: The type of the client (Unregistered or Camera)
        :param messageID: The id of the message, i.e. the key for the protocol
            rule to run.
        :param cameraID: The camera ids for the clients to send the message to.
        :return: Nothing
        """
        self.sendToSelects(server, clientType, messageID, [cameraID], *args)

    def sendToSelects(self,
                      server: CameraServer,
                      clientType: str,
                      messageID: str,
                      cameraIDs: Iterable[str],
                      *args) -> None:
        """Sends a message to clients with a specific type with on of many ids.

        :param server: The server object handling the clients.
        :param clientType: The type of the clients (Unregistered or Camera)
        :param messageID: The id of the message, i.e. the key for the protocol
            rule to run.
        :param cameraIDs: A list of the camera ids for the clients to send the
            message to.
        :return: Nothing
        """
        cameraIDs = set(cameraIDs)
        # noinspection PyTypeChecker
        for client in self.clients[clientType].values():
            if client.cameraID in cameraIDs:
                client.send(server, messageID, *args)
                if messageID == "stop previewing" and client.previewSocket is not None:
                    client.previewSocket.close()


def makeClient(server: CameraServer,
               clientSocket: socket.socket,
               clientType: str,
               clientProtocol: protocol.Protocol,
               *args) -> 'ClientController':
    """A factory function for clients.

    This function is needed because when a client connects, its handshake
    introduces itself as a given type of client, and the string representing
    that client type needs to be mapped to the appropriate object.

    A camera client should have 4 or five extra parameters, where it should be
    cageID, cameraID, cameraView and cageName. If there are five parameters,
    it should come before all the others and be the client version, but is
    currently ignored.

    :param server: The server to register the client to.
    :param clientSocket: The socket used to communicate with the actual client.
    :param clientType: The type this client is (Unregistered or Camera).
    :param clientProtocol: The protocol that this client should use when
        communicating.
    :return: An UnregisteredClient if the type is Unregistered with the given
        parameters, or a CameraClient if the type is Camera with the given
        parameters and the additional args.
    """
    if clientType == 'Unregistered':
        return UnregisteredClient(server, clientSocket, clientProtocol)
    elif clientType == 'Camera':
        return CameraClient(server, clientSocket, clientProtocol, *args)
    else:
        raise Exception('clientType must be either "Unregistered", ' +
                        '"Camera"')


class ClientController:
    """Parent class for client objects.

    All client controller objects can both send and handle (react to)
    messages.
    """

    def __init__(self, server, clientSocket, clientProtocol):
        # Relevant overall client information
        self.server = server  # type: CameraServer
        self.socket = clientSocket  # type: socket.socket
        self.protocol = clientProtocol  # type: protocol.Protocol
        self.buffer = b''  # type: bytes

    def send(self, server: CameraServer, messageID: str, *args) ->None:
        """Send a message with the given ID to the client.

        :param server: The server sending the message.
        :param messageID: The ID of the message, i.e. the key which is the
            index of the handler that is being requested.
        :return: Nothing
        """
        message = self.protocol.buildMessage(messageID, server, self, *args)
        try:
            self.socket.sendall(message)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug('{} <- {}'.format(self.socket.getpeername()[0],
                                               protocol.Syntax.formatMessage(
                                                       message)))
        except OSError:
            logger.error('ERROR sending message {} to {}'.format(messageID,
                                                                 self.socket))

    def handle(self, server: CameraServer, buffer: bytes) -> None:
        """Handle messages in the buffer.

        The buffer can contain multiple concatenated messages, or partial
        messages.

        :param server: The server object controlling this client and receiving
            the buffer.
        :param buffer: A buffer send from the client.
        :return: Nothing
        """
        self.buffer += buffer
        self.buffer = self.protocol.handleBuffer(self.buffer, server, self)
        if logger.isEnabledFor(logging.DEBUG):
            for message in \
                    protocol.Syntax.formatMessage(buffer).split(');')[:-1]:
                logger.debug('{} -> {}'.format(self.socket.getpeername()[0],
                                               message + ');'))


class UnregisteredClient(ClientController):
    """A client whose type is unknown."""

    def __init__(self, server, clientSocket, clientProtocol):
        ClientController.__init__(self, server, clientSocket, clientProtocol)
        self.clientType = 'Unregistered'  # type: str


class CameraClient(ClientController):
    """A client connection to a Raspberry Pi camera unit."""

    def __init__(self, server, clientSocket, clientProtocol, *args):
        ClientController.__init__(self, server, clientSocket, clientProtocol)
        self.clientType = 'Camera'  # type: str
        # Time stamp queue
        self.timestamps = queue.Queue()  # type: queue.Queue
        # socket for previewing (So we can close later)
        self.previewSocket = None  # type: socket.socket
        self.previewPort = None  # type: int
        if len(args) == 4:
            self.cageID = args[0]  # type: str
            self.cameraID = args[1]  # type: str
            self.cameraView = args[2]  # type: str
            self.cageName = args[3]  # type: str
        elif len(args) == 5:
            self.cageID = args[1]  # type: str
            self.cameraID = args[2]  # type: str
            self.cameraView = args[3]  # type: str
            self.cageName = args[4]  # type: str
        logger.info('Camera: {}'.format(self.cameraID))
        # Send handshake response
        self.send(server, 'handshake')
        self.recording = False
        self.send(server, 'set FPS')
        self.send(server, 'set vflip')
        self.send(server, 'set color mode')
        self.send(server, 'set autogain')
        self.send(server, 'set gain')
        self.send(server, 'set ISO')
        self.send(server, 'set brightness')
        self.send(server, 'set rotation')
        self.send(server, 'set zoom points')
        self.send(server, 'set camMap')
        self.send(server, 'set compression')
        # Notify this camera of siblings and vice-versa
        for sibling in server.clients.getClients('Camera'):
            if sibling.socket.getpeername()[0] != self.socket.getpeername()[0]:
                sibling.send(server, 'sibling',
                             self.socket.getpeername()[0])
                self.send(server, 'sibling', sibling.socket.getpeername()[0])

    def getFreeSocket(self) -> socket.socket:
        """Function will get a free socket that can be used.

        :return: A new socket after storing it in ``previewSocket``
        """
        freeSocket = socket.socket()
        freeSocket.bind(('', 0))
        self.previewSocket = freeSocket
        self.previewPort = freeSocket.getsockname()[1]
        return freeSocket

    def streamVideoToFile(self, filename: str, width: int, height: int) -> int:
        """Stream a video from this camera client to the given filename.

        This is done asynchronously because there is a scalable number of pis,
        and includes conversion from H.264 to MP4 video if necessary.

        :param filename: The name of the file to stream to.
        :param width: The width of the image being captured (used to create
            missing headers if they ever happen).
        :param height: The height of the image being captured (used to create
            missing headers if they ever happen).
        :return: The port of the socket for the stream.
        """

        def findSPSHeader(buffer: bytes) -> int:
            """Returns the location of the first SPS header in the buffer.

            :param buffer: The buffer to find the SPS header.
            :return: The index in the given buffer of the SPS header.
            """
            return buffer.find(StreamThread.SPSHeader)

        class StreamThread(threading.Thread):
            """Asynchronous streaming thread for videos."""
            SPSHeader = bytes.fromhex('0000000127')
            PPSHeader = bytes.fromhex('0000000128')

            # noinspection PyShadowingNames
            def __init__(self, server, client, filename, clientSocket, width, height):
                threading.Thread.__init__(self)
                self.server = server  # type: CameraServer
                self.client = client
                self.filename = filename
                self.width = width
                self.height = height

                self.socket = clientSocket
                self.daemon = True
                self.byteRate = []

            def downloadVideo(self) -> bool:
                """Threads inner method to download a video. This method is called in run.

                :return: ``True`` if the download finished without exceptions.
                """
                connection = self.socket.accept()[0]
                inputStream = connection.makefile('br')
                outputFile = open(self.filename, 'bw')
                bytesReadSinceSPSHeader = 0
                buffer = inputStream.read(8196)
                logger.debug('File {} at time {}'.format(self.filename, time.strftime('%H:%M:%S')))
                while buffer:
                    spsHeaderIndex = findSPSHeader(buffer)
                    if spsHeaderIndex > -1:
                        bytesReadSinceSPSHeader += spsHeaderIndex
                        self.byteRate.append(bytesReadSinceSPSHeader)
                        bytesReadSinceSPSHeader = 0
                    outputFile.write(buffer)
                    buffer = inputStream.read(8196)
                # Close everything up
                connection.close()
                self.socket.close()
                outputFile.close()
                return True

            def run(self) -> None:
                """Start the thread to download a client's video"""
                if self.downloadVideo():
                    finishTime = self.client.timestamps.get()
                    self.client.timestamps.task_done()
                    if self.server.options.format == 'h264':
                        newfilename = self.filename.rstrip('h264') + 'mp4'
                        gpac.makeMP4(self.filename, newfilename,
                                     self.server.clientOptions.fps,
                                     self.width,
                                     self.height)
                        self.filename = newfilename
                    time.sleep(1)
                    numFrames = gpac.getNumFrames(self.filename)
                    self.server.downloadFinished(
                            self.filename, numFrames, utils.convertTimestamp(
                                    finishTime))

        streamSocket = socket.socket()
        streamSocket.bind(('', 0))
        streamSocket.listen(1)
        streamThread = StreamThread(self.server, self, filename, streamSocket,
                                    width, height)
        streamThread.start()
        return streamSocket.getsockname()[1]


class KeyboardThread(threading.Thread):
    """A thread handling command-line user input. This thread is technically not
    needed but can be used for debugging if the GUI break down.
    """

    def __init__(self, controller):
        threading.Thread.__init__(self)
        self.daemon = True
        self.controller = controller

    def run(self) -> None:
        """Loops infinitely listening for r to to toggle recording and q to quit."""
        try:
            while True:
                # Videos recorded will show up in the same folder as this file
                print('Press enter r to toggle recording')
                choice = input()
                if choice == 'r':
                    self.controller.toggleRecording()
                if choice == 'q':
                    self.controller.close()
                time.sleep(1)
        except KeyboardInterrupt:
            self.controller.close()


def getBroadcastAddress(address: str, mask: str) -> str:
    """Get address that will reach everyone on local network

    :param address: The address of a device on the network looking for a
        broadcast address.
    :param mask: The bitmask for the network, as either number of bits or
        formatted like an IP address (e.g. 24 vs 255.255.255.0)
    :return: the address to send a UDP broadcast packet to reach everyone on
        the local network
    """
    return ipaddress.IPv4Network(address + '/' + mask,
                                 False).broadcast_address.compressed


def get_ip_address(ifname: str='wlan0') -> Union[Dict[str, str], List[str]]:
    """
    This function is used to pull the local ip associated from an interface.
    This code is in the creative commons (CC-BY-SA) and can be found at
    http://stackoverflow.com/questions/24196932/how-can-i-get-the-ip-address-of-eth0-in-python

    :param ifname: The name of the network device to check (for linux).
    :return: A dict specifying the data related to the ip address of the
        computer.
    """

    if platform.system() == 'Windows':
        import subprocess
        #s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        data = defaultdict(list)
        with subprocess.Popen('ipconfig', stdout=subprocess.PIPE) as sp:
            for line in sp.stdout.read().decode().splitlines():
                line = line.lstrip().rstrip()  # type: str
                if ': ' not in line:
                    continue
                if line.startswith('Connection-specific DNS Suffix'):
                    data['csds'].append(line.rsplit(': ', 1)[1])
                elif line.startswith('Link-local IPv6 Address'):
                    data['ipv6'].append(line.rsplit(': ', 1)[1])
                elif line.startswith('IPv4 Address'):
                    data['ipv4'].append(line.rsplit(': ', 1)[1])
                elif line.startswith('Subnet Mask'):
                    data['mask'].append(line.rsplit(': ', 1)[1])
                elif line.startswith('Default Gateway'):
                    data['gate'].append(line.rsplit(': ', 1)[1])
        if 'ipv4' not in data or 'mask' not in data:
            # probably not good
            pass
        return data
    elif platform.system() == 'Linux':
        import subprocess
        data = defaultdict(list)
        count = 0
        with subprocess.Popen(['ifconfig', '-a'], stdout = subprocess.PIPE) as sp:
            for line in sp.stdout.read().decode().splitlines():
                line = line.lstrip().rstrip()
                print(line)
                if line.startswith('eth0') and line.find('RUNNING'):
                    count = 2
                elif line.startswith('inet') and count == 2:
                    data['ipv4'].append(line.rsplit()[1])
                    data['mask'].append(line.rsplit()[3])
                    count = 1
                    break

        if count == 1:
            path = "/etc/resolv.conf"
            with open(path) as fp:
                all_line = fp.readline()
                cnt = 1
                while not all_line.startswith('search'):
                    all_line = fp.readline()
                else:
                    data['csds'].append(all_line.rsplit()[1])
                fp.close()
        if 'ipv4' not in data or 'mask' not in data:
            # probably not good
            pass
        return data
    else:
        raise OSError('SCORHE Acquisition does not support your system: {}'.format(platform.system()))

class AdvertThread(threading.Thread):
    """Advertises this server's IP address on the network

    Uses UDP broadcast packets to send alert to everyone on the network that
    the server is up and running. Computers running the SCORHE_client software
    will detect these messages and connect automatically.
    """

    def __init__(self, port=8890):
        threading.Thread.__init__(self)
        self.daemon = True
        self.port = port

    def run(self) -> None:
        """Resolves broadcast addresses on the network and broadcasts its ip and port infinitely."""
        ipData = get_ip_address()

        # this regex prevents broadcasting while connected to the nih network,
        # or any time the computer is connected to anything that isn't a linksys
        # router. in theory.
        csds_re = re.compile('router[0-9a-f]{6}\.com')
        if 'csds' not in ipData:
            logger.info('Not broadcasting.')
            return
        for i in range(0, len(ipData['csds'])):
            if csds_re.match(ipData['csds'][i]):
                break
        else:
            logger.info('Not broadcasting.')
            return
        ip = ipData['ipv4'][i]
        mask = ipData['mask'][i]
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM,
                          socket.IPPROTO_UDP)
        s.bind(('', 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        broadcast = getBroadcastAddress(ip, mask)
        while True:
            s.sendto(ip.encode(), (broadcast, self.port))
            time.sleep(5)


        

class PokeThread(threading.Thread):
    """Send pokes to ensure connections are alive.

    This thread simply sends a "poke" message every minute to each client,
    ensuring that the connection is still alive (there are some rare
    circumstances where a socket can disconnect without notification, and a
    periodic poke can proactively detect such cases)
    """

    def __init__(self, server):
        threading.Thread.__init__(self)
        self.daemon = True
        self.server = server

    def run(self) -> None:
        """Pokes the client every 60 seconds, forever."""
        while True:
            time.sleep(60)
            self.server.sendToAll('Camera', 'poke')


def masterRunServer(argv: List[str]) -> Tuple[CameraServerController, ServerThread]:
    """Function that launches the whole server.

    :param argv: The command line arguments passed to the program. Used for
        dictating some settings for the server. See parseArgv for more details.
    :return: The threads for the controller and the server.
    """
    # Get args if running from command line
    serverOptions = parseArgv(argv)  # type: ServerOptions
    # Start Broadcasting out to whole network
    broadcastThread = AdvertThread()
    # Start the Server controller
    controllerThread = CameraServerController(serverOptions)
    # Start the actual server
    serverThread = ServerThread(controllerThread.server)
    # If the server is being launched via command line how to handle keyboard  
    keyboardThread = KeyboardThread(controllerThread)
    keyboardThread.start()  # doesnt broadcast, so it's ok
    # Keep the connections alive by poking
    pokeThread = PokeThread(controllerThread.server)

    broadcastThread.start()
    controllerThread.start()
    serverThread.start()
    pokeThread.start()

    return controllerThread, serverThread


def main(argv: List[str]) -> None:
    """This main method just runs the master start function.

    :param argv: The command line arguments passed to the program. Used for
        dictating some settings for the server. See masterRunServer and
        parseArgv for more details.
    """
    controllerThread, serverThread = masterRunServer(argv)
    for thread in [controllerThread, serverThread]:
        thread.join()
    logger.info('Shut down successful')


if __name__ == '__main__':
    print('{} v{}'.format(NAME, VERSION))
    main(sys.argv[1:])
