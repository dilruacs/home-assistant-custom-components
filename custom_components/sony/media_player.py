"""
Support for interface with a Sony MediaPlayer TV.

For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/media_player.braviatv/
"""
import functools
import logging
import voluptuous as vol

from homeassistant.components.media_player import (
    MediaPlayerDevice, PLATFORM_SCHEMA)
from homeassistant.components.media_player.const import (
    SUPPORT_NEXT_TRACK, SUPPORT_PAUSE, SUPPORT_PREVIOUS_TRACK, SUPPORT_TURN_ON,
    SUPPORT_TURN_OFF, SUPPORT_PLAY,SUPPORT_PLAY_MEDIA, SUPPORT_STOP)
from homeassistant.const import (CONF_HOST, CONF_NAME, STATE_OFF, STATE_ON,
    STATE_PLAYING, STATE_PAUSED)
import homeassistant.helpers.config_validation as cv

from homeassistant.util.json import load_json, save_json

REQUIREMENTS = ['sonyapilib==0.3.10']

SONY_CONFIG_FILE = 'sony.conf'

CLIENTID_PREFIX = 'HomeAssistant'

DEFAULT_NAME = 'Sony Media Player'

NICKNAME = 'Home Assistant'

# Map ip to request id for configuring
_CONFIGURING = {}

_LOGGER = logging.getLogger(__name__)

SUPPORT_SONY = SUPPORT_PAUSE | \
                 SUPPORT_PREVIOUS_TRACK | SUPPORT_NEXT_TRACK | \
                 SUPPORT_TURN_ON | SUPPORT_TURN_OFF | \
                 SUPPORT_PLAY | SUPPORT_PLAY_MEDIA | SUPPORT_STOP

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_HOST): cv.string,
    vol.Required(CONF_NAME, default=DEFAULT_NAME): cv.string,
})


# pylint: disable=unused-argument
def setup_platform(hass, config, add_devices, discovery_info=None):
    """Set up the Sony Media Player platform."""
    host = config.get(CONF_HOST)

    if host is None:
        return

    pin = None
    sony_config = load_json(hass.config.path(SONY_CONFIG_FILE))
    from sonyapilib.device import SonyDevice

    while sony_config:
        # Set up a configured TV
        host_ip, host_config = sony_config.popitem()
        if host_ip == host:
            device = SonyDevice.load_from_json(host_config['device'])
            hass_device = SonyMediaPlayerDevice(
                host, device.nickname, device.pin, device.mac)
            hass_device.sonydevice = device
            add_devices([hass_device])
            return

    setup_sonymediaplayer(config, pin, hass, add_devices)


def setup_sonymediaplayer(config, pin, hass, add_devices):
    """Set up a Sony Media Player based on host parameter."""
    host = config.get(CONF_HOST)
    name = config.get(CONF_NAME)

    if pin is None:
        request_configuration(config, hass, add_devices)
        return
    else:
        # If we came here and configuring this host, mark as done
        if host in _CONFIGURING:
            request_id = _CONFIGURING.pop(host)
            configurator = hass.components.configurator
            configurator.request_done(request_id)
            _LOGGER.info("Discovery configuration done")

        hass_device = SonyMediaPlayerDevice(host, name, pin)

        # Save config, we need the mac address to support wake on LAN
        save_json(
            hass.config.path(SONY_CONFIG_FILE), {host: {
                'device': hass_device.sonydevice.save_to_json()}})

        add_devices([hass_device])


def request_configuration(config, hass, add_devices):
    """Request configuration steps from the user."""
    host = config.get(CONF_HOST)
    name = config.get(CONF_NAME)

    configurator = hass.components.configurator

    # We got an error if this method is called while we are configuring
    if host in _CONFIGURING:
        configurator.notify_errors(
            _CONFIGURING[host], "Failed to register, please try again.")
        return

    def sony_configuration_callback(data):
        """Handle the entry of user PIN."""

        from sonyapilib.device import SonyDevice, AuthenicationResult

        pin = data.get('pin')
        sony_device = SonyDevice(host, name)

        auth_mode = sony_device.get_action("register").mode
        authenticated = False

        # make sure we only send the authentication to the device
        # if we have a valid pin
        if pin == '0000' or pin is None or pin == '':
            register_result = sony_device.register()
            if register_result == AuthenicationResult.SUCCESS:
                authenticated = True
            elif register_result == AuthenicationResult.PIN_NEEDED:
                # return so next call has the correct pin
                return
            else:
                _LOGGER.error("An unknown error occured during registration")

        _LOGGER.debug("auth_mode: %d - pin: %s", auth_mode, pin)

        # devices below version 3 do not require a pin.
        if auth_mode > 3:
            authenticated = sony_device.send_authentication(pin)

        if authenticated:
            setup_sonymediaplayer(config, pin, hass, add_devices)
        else:
            request_configuration(config, hass, add_devices)

    _CONFIGURING[host] = configurator.request_config(
        name, sony_configuration_callback,
        description='Enter the Pin shown on your Sony Device. ' +
        'If no Pin is shown, enter 0000 ' +
        'to let the device show you a Pin.',
        description_image="/static/images/smart-tv.png",
        submit_caption="Confirm",
        fields=[{'id': 'pin', 'name': 'Enter the pin', 'type': ''}]
    )



class SonyMediaPlayerDevice(MediaPlayerDevice):
    """Representation of a Sony mediaplayer"""

    def __init__(self, host, name, pin, mac=None):
        """
        Initialize the Sony mediaplayer device.
        Mac address is optional but neccessary for wake on LAN
        """
        from sonyapilib.device import SonyDevice

        self._pin = pin
        self.sonydevice = SonyDevice(host, name)
        self._name = name
        self._state = STATE_OFF
        self._muted = False
        self._id = None
        self._playing = False

        self.sonydevice.pin = pin
        self.sonydevice.mac = mac

        try:
            self.sonydevice.update_service_urls()
            self.update()
        except Exception as exception_instance:  # pylint: disable=broad-except
            self._state = STATE_OFF

    def update(self):
        """Update TV info."""
        if not self.sonydevice.get_power_status():
            self._state = STATE_OFF
            return
        else:
            self._state = STATE_ON

        # Retrieve the latest data.
        try:
            if self._state == STATE_ON:
                power_status = self.sonydevice.get_power_status()
                if power_status:
                    playback_info = self.sonydevice.get_playing_status()
                    if playback_info == "PLAYING":
                         self._state = STATE_PLAYING
                    elif playback_info == "PAUSED_PLAYBACK":
                        self._state = STATE_PAUSED
                    else:
                        self._state = STATE_ON
                else:
                    self._state = STATE_OFF

        except Exception as exception_instance:  # pylint: disable=broad-except
            _LOGGER.error(exception_instance)
            self._state = STATE_OFF

    @property
    def name(self):
        """Return the name of the device."""
        return self._name

    @property
    def state(self):
        """Return the state of the device."""
        return self._state

    @property
    def supported_features(self):
        """Flag media player features that are supported."""
        return SUPPORT_SONY

    @property
    def media_title(self):
        """Title of current playing media."""
        # the device used for testing does not send any
        # information about the media which is played
        return ""
    @property
    def media_content_id(self):
        """Content ID of current playing media."""
        return ""

    @property
    def media_duration(self):
        """Duration of current playing media in seconds."""
        return ""

    def turn_on(self):
        """Turn the media player on."""
        self.sonydevice.power(True)

    def turn_off(self):
        """Turn off media player."""
        self.sonydevice.power(False)

    def media_play_pause(self):
        """Simulate play pause media player."""
        if self._playing:
            self.media_pause()
        else:
            self.media_play()

    def media_play(self):
        """Send play command."""
        self._state = STATE_PLAYING
        self.sonydevice.play()

    def media_pause(self):
        """Send media pause command to media player."""
        self._state = STATE_PAUSED
        self.sonydevice.pause()

    def media_next_track(self):
        """Send next track command."""
        self.sonydevice.next()

    def media_previous_track(self):
        """Send the previous track command."""
        self.sonydevice.prev()

    def media_stop(self):
        """Send stop command."""
        self.sonydevice.stop()
