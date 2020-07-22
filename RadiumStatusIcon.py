import rumps
class RadiumStatusIcon(rumps.App):
    def __init__(self, radiumInst):
        self.inst = radiumInst

        super(RadiumStatusIcon, self).__init__("Radium " + radiumInst.versionStr, icon="./LogoMini.png")
        self.buttons = {
            "pause": rumps.MenuItem("Paused"),
            "loop": rumps.MenuItem("Loop"),
            "autoplay": rumps.MenuItem("Autoplay"),
            "clearQueue": rumps.MenuItem("Queue Size: 0"),
            "rebuildData": rumps.MenuItem("Rebuild Database"),
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