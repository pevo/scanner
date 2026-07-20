"""HTTPS static server for the Plate folder (for iPhone testing on the LAN).

Usage:  python serve_https.py [port]      (default 8443)
Cert:   certs/cert.pem + certs/key.pem    (generated with mkcert)
Phone:  install certs/mkcert-rootCA.pem once, then open https://<PC-IP>:8443/scanner.html
"""
import http.server
import os
import ssl
import sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8443


class Handler(http.server.SimpleHTTPRequestHandler):
    # Windows registry can map these wrong; module scripts + PWA need exact types
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".js": "text/javascript",
        ".mjs": "text/javascript",
        ".wasm": "application/wasm",
        ".webmanifest": "application/manifest+json",
        ".tflite": "application/octet-stream",
        ".pem": "application/x-x509-ca-cert",   # so iOS offers to install the root CA
    }

    def end_headers(self):
        # Cross-origin isolation -> SharedArrayBuffer -> multi-threaded wasm.
        # Without these the LiteRT/XNNPACK wasm backend runs single-threaded,
        # which on iOS (no JSPI, so the detector is CPU-only) is the main reason
        # inference is slow. All app resources are same-origin, so require-corp
        # doesn't block them; verify crossOriginIsolated===true in the Settings
        # diagnostics line on the phone.
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        super().end_headers()


ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ctx.load_cert_chain("certs/cert.pem", "certs/key.pem")
srv = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
print(f"Serving {os.getcwd()}")
print(f"  scanner:  https://192.168.0.11:{PORT}/scanner.html")
print(f"  root CA:  https://192.168.0.11:{PORT}/certs/mkcert-rootCA.pem")
srv.serve_forever()
