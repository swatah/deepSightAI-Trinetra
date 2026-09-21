import sys
import gi

gi.require_version('Gst', '1.0')
gi.require_version('GstRtspServer', '1.0')
from gi.repository import Gst, GstRtspServer, GLib

Gst.init(None)

class TestServerFactory(GstRtspServer.RTSPMediaFactory):
    def __init__(self, **properties):
        super(TestServerFactory, self).__init__(**properties)

  
        if sys.platform == "darwin":    
            src_element = "avfvideosrc"
        elif sys.platform == "linux":   
            src_element = "v4l2src device=/dev/video0"
        elif sys.platform == "win32":   
            src_element = "ksvideosrc"
        else:
            raise RuntimeError("Unsupported OS for webcam capture")

        # Define the GStreamer pipeline to be used
        self.launch_string = (
            f'( {src_element} ! videoconvert ! x264enc speed-preset=ultrafast tune=zerolatency ! '
            'rtph264pay name=pay0 pt=96 )'
        )

    # This function is called by the RTSP server to create the pipeline
    def do_create_element(self, url):
        return Gst.parse_launch(self.launch_string)

class GstServer(GstRtspServer.RTSPServer):
    def __init__(self, **properties):
        super(GstServer, self).__init__(**properties)
        self.factory = TestServerFactory()
        self.get_mount_points().add_factory("/test", self.factory)
        self.attach(None)

if __name__ == '__main__':
    print("Starting RTSP server...")
    print("Stream will be available at rtsp://<YOUR_IP_ADDRESS>:8554/test")
    
    server = GstServer()
    loop = GLib.MainLoop()
    loop.run()