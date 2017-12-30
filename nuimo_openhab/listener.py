import sys
import logging
import time

import nuimo
import requests
from openhab import openHAB

import nuimo_menue
from nuimo_openhab.util import config


class OpenHabItemListener(nuimo_menue.model.AppListener):

    def __init__(self, openhab: openHAB):
        self.openhab = openhab
        self.widgets = []
        self.sliderWidgets = []

        # Reminds changes that are too little to directly expose them to OpenHab (if the wheel is turned very slow)
        self.reminder = 0.0

        # Caches the last dimmer item state, because the OpenHab REST API is too sluggish when the wheel is turned fast
        self.lastDimmerItemState = 0
        self.lastDimmerItemTimestamp = 0

    def addWidget(self, widget):
        if widget["type"] == "Slider":
            self.sliderWidgets.append(widget)
        else:
            self.widgets.append(widget)

    def received_gesture_event(self, event):
        if event.gesture == nuimo.Gesture.ROTATION:
            return self.handleRotation(event)
        else:
            return self.handleCommonGesture(event)

    def handleCommonGesture(self, event):
        gestureResult = None

        for widget in self.widgets:
            namespace = "OPENHAB." + widget["type"]
            mappedCommands = config.get_mapped_commands(gesture=event.gesture, namespace=namespace)
            # Add additional commands defined via custom mapping
            customCommand = self.resolveCustomMappings(widget["mappings"], event.gesture.name)
            if customCommand is not None:
                mappedCommands.append(customCommand)

            logging.debug("Mapped command openHAB: " + str(mappedCommands) + "(requested namespace: " + namespace + ")")

            for command in mappedCommands:
                # Special handling for mappings:
                # On custom switches (=switches with mappings), mapped commands have another meaning:
                # they define "extra mapping labels" that CAN be used within mappings, but don't have to
                # if those extra mapping labels are not used within the current widget, command is resolved as None and skipped
                if widget["type"] == "CustomSwitch" and command != customCommand:
                    command = self.resolveCustomMappings(widget["mappings"], command)

                # Special handling for TOGGLE: Resolve state first to be able showing the correct action icon
                if command == "TOGGLE":
                    state = requests.get(self.openhab.base_url + "/items/" + widget["item"]["name"] + "/state").text
                    if state in config["toggle_mapping"]:
                        command = config["toggle_mapping"][state]
                    else:
                        logging.warning("There is no toggle counterpart known for state '"+state+"'. Skip TOGGLE command.")

                if command is not None:
                    self.openhab.req_post("/items/" + widget["item"]["name"], command)
                    # Push back command executed, full qualified command for action icon
                    gestureResult = namespace + "." + command

            return gestureResult

    def resolveCustomMappings(self, mappings, command: str):
        for mapping in mappings:
            if mapping["label"] == command:
                return mapping["command"]
            # Workaround for toggling players
            elif mapping["label"] == ">" and command == "TOGGLEIFPLAYER":
                return "TOGGLE"

    def handleRotation(self, event):
        for widget in self.sliderWidgets:
            valueChange = event.value / 30
            self.reminder += valueChange
            if (abs(self.reminder) >= 1):
                self.openhab.req_post("/items/" + widget["item"]["name"], "REFRESH")
                logging.debug(self.openhab.base_url + widget["item"]["name"] + "/state")
                try:
                    currentTimestamp = int(round(time.time() * 1000))
                    if (self.lastDimmerItemTimestamp < currentTimestamp-3000):
                        itemStateRaw = requests.get(self.openhab.base_url + "/items/" + widget["item"]["name"] + "/state").text
                        currentState = float(itemStateRaw)
                        if (currentState < 0):
                            currentState = 0
                        if (currentState < 1):
                            currentState *= 100
                        currentState = int(currentState)
                        logging.debug("Raw item state: "+itemStateRaw)
                    else:
                        currentState = self.lastDimmerItemState
                    logging.debug("Old state: " + str(currentState))
                    newState = currentState+round(self.reminder)
                    if (newState < 0):
                        newState = 0
                    if (newState > 100):
                        newState = 100

                    logging.debug("New state: " + str(newState))

                    self.lastDimmerItemState = newState
                    self.lastDimmerItemTimestamp = currentTimestamp

                    self.openhab.req_post("/items/" + widget["item"]["name"], str(newState))
                except Exception:
                    newState = 0
                    logging.error(sys.exc_info())
                finally:
                    self.reminder = 0
        return self.lastDimmerItemState