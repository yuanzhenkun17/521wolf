from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class NoCacheHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()


if __name__ == "__main__":
    dist = Path(__file__).with_name("dist")
    handler = lambda *args, **kwargs: NoCacheHandler(*args, directory=str(dist), **kwargs)
    server = ThreadingHTTPServer(("127.0.0.1", 8767), handler)
    print("Serving http://127.0.0.1:8767")
    server.serve_forever()
