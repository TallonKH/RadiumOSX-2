import rumps
class RadiumStatusIcon(rumps.App):
    def __init__(self, radiumInst):
        self.inst = radiumInst

        super(RadiumStatusIcon, self).__init__("Radium " + radiumInst.versionStr, icon="./LogoMini.png")
        self.buttons = {
            "pause": rumps.MenuItem("Paused", callback=self.inst.togglePaused),
            "loop": rumps.MenuItem("Loop", callback=self.inst.toggleLooping),
            "autoplay": rumps.MenuItem("Autoplay", callback=self.inst.toggleAutoplay),
            "clearQueue": rumps.MenuItem("Clear queue (0)", callback=self.inst.clearQueue),
            "rebuildData": rumps.MenuItem("Rebuild Database", callback=self.inst.rebuildAll),
            "volume": rumps.MenuItem("Volume: 100%"),
            "song": rumps.MenuItem("----"),
            "songLength": rumps.MenuItem("----"),
            "activeSongs": rumps.MenuItem("----")
        }

        self.buttons["autoplay"].state = True

        self.menu = [
            self.buttons["pause"],
            self.buttons["loop"],
            self.buttons["autoplay"],
            self.buttons["clearQueue"],
            None,
            self.buttons["volume"],
            self.buttons["song"],
            self.buttons["songLength"],
            self.buttons["activeSongs"],
            None,
            self.buttons["rebuildData"]
        ]