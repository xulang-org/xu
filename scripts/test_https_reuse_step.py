#!/usr/bin/env python3
"""
Step-by-step verification of net/http HTTPS connection reuse:
1. Reusing idle HTTPS connection:
   - Two consecutive HTTPS GET requests to the same endpoint use the same connection.
   - Server counts exactly 1 TLS handshake for both requests.
   - client.has_idle_connection() returns true after request.
2. Explicit connection cleanup:
   - client.close_idle_connections() closes the cached TLS connection.
   - client.has_idle_connection() returns false.
3. Server-initiated close:
   - Request to endpoint returning 'Connection: close' closes the connection.
   - client.has_idle_connection() returns false.
4. Target isolation:
   - Making request to a different host/port closes prior connection and connects anew.
"""

import base64
import http.server
import os
import socketserver
import ssl
import subprocess
import sys
import tempfile
import threading
import time

XU_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
COMPILER = os.path.join(XU_ROOT, "bin", "xu.exe" if os.name == "nt" else "xu")
STDLIB_SRC = os.path.join(XU_ROOT, "src")

RSA_CERT_B64 = (
    'LS0tLS1CRUdJTiBDRVJUSUZJQ0FURS0tLS0tCk1JSUM4RENDQWRpZ0F3SUJBZ0lCQkRBTkJna3Foa2lHOXcwQkFR'
    'c0ZBREFVTVJJd0VBWURWUVFEREFsc2IyTmgKYkdodmMzUXdJQmNOTWpBd01UQXhNREF3TURBd1doZ1BNakE1T1RB'
    'eE1ERXdNREF3TURCYU1CUXhFakFRQmdOVgpCQU1NQ1d4dlkyRnNhRzl6ZERDQ0FTSXdEUVlKS29aSWh2Y05BUUVC'
    'QlFBRGdnRVBBRENDQVFvQ2dnRUJBSmVsCityOFlGKzJtcUxQV3p4bDRJYnp5Y0ozNUN5V3pUUFpqYm9SQlNwYVFK'
    'RjdmckZFc04wZmFreC93TTQyZ3dkdFcKc1B6YkVjekFrRnRUQWxwUVl1bk50TUtMbWhWZUw2bERmQyt4Y0xhejlq'
    'V0ZJU2hjYjNNUHdwNGlXd1I0K3ZxcQprN0hINm5URmFkZll2ZVloaHU4dEdqU2FVeGtTVDVKZ1pIMWRFTWppbEEr'
    'bmNKR1hodW8zQnNpaXVwKzZsMnR5Cjd6QWJHaGt1aGY3a05mK0ZHU3c1SWRsWU1CdnlreGNGMHpmZFdqcGhTTU9m'
    'VDdWRDMvWTYyQXFsRy9DU2NrV0EKK2VzUDcvd3MrKy9tUmJ5VHNzcmFML21NTDJTK0FSK01YWTdTTUE2UWNaUUMy'
    'dkdtbWxhMUtRaVNjQUJQcFh0VwpPTWprYWtFbDk4ZWJQYXVuVlJFQ0F3RUFBYU5MTUVrd0RBWURWUjBUQVFIL0JB'
    'SXdBREFPQmdOVkhROEJBZjhFCkJBTUNCYUF3RkFZRFZSMFJCQTB3QzRJSmJHOWpZV3hvYjNOME1CTUdBMVVkSlFR'
    'TU1Bb0dDQ3NHQVFVRkJ3TUIKTUEwR0NTcUdTSWIzRFFFQkN3VUFBNElCQVFCMVJwVVdRc0NUVXU1R3M2bkZYQ2pH'
    'NHhRenJ2WTl1TTB5Mm1HZQpUVWJHditqQ3JaUTVXbzFDUUZKaTlYY1ErTnBSbVBRdU4xdVVYaUJteVVLRnVRNWhE'
    'Y1d0blpKZkFjNE56RVdVCkg2blVsVjdoRVF3NlR4SkRkUlJVVXd0S1hkbmpOa1o0VWNIWTRNTi9XQVVrTER0bXN5'
    'd1d2T0g0WFcvZXJTUXEKNkJTaEVLczJvU09JdzI2d2czZzdPcDM3YUJrb0V6ZlVmKzJZaDRseC9wbTFIRFBickJm'
    'RTJ4aUNjK3NqbWkrNgpQOG1MQStnSEorRVpRTmJkMk9DK3J2ekpkaE1CUkcra0tnZDBsRjR4RU5ScXpXanltYXRV'
    'RjFxak03aVE2TWc3CkN5Zkl0ZnkvUVIwcUZUZTFsWmhRRzhiMVdjOWtrU3ZUWUtISFZEL1ZpRU9jazU2UQotLS0t'
    'LUVORCBDRVJUSUZJQ0FURS0tLS0tCg=='
)
RSA_KEY_B64 = (
    'LS0tLS1CRUdJTiBQUklWQVRFIEtFWS0tLS0tCk1JSUV2UUlCQURBTkJna3Foa2lHOXcwQkFRRUZBQVNDQktjd2dn'
    'U2pBZ0VBQW9JQkFRQ1hwZnEvR0JmdHBxaXoKMXM4WmVDRzg4bkNkK1FzbHMwejJZMjZFUVVxV2tDUmUzNnhSTERk'
    'SDJwTWY4RE9Ob01IYlZyRDgyeEhNd0pCYgpVd0phVUdMcHpiVENpNW9WWGkrcFEzd3ZzWEMycy9ZMWhTRW9YRzl6'
    'RDhLZUlsc0VlUHI2cXBPeHgrcDB4V25YCjJMM21JWWJ2TFJvMG1sTVpFaytTWUdSOVhSREk0cFFQcDNDUmw0YnFO'
    'd2JJb3JxZnVwZHJjdTh3R3hvWkxvWCsKNURYL2hSa3NPU0haV0RBYjhwTVhCZE0zM1ZvNllVakRuMCsxUTkvMk90'
    'Z0twUnZ3a25KRmdQbnJEKy84TFB2dgo1a1c4azdMSzJpLzVqQzlrdmdFZmpGMk8wakFPa0hHVUF0cnhwcHBXdFNr'
    'SWtuQUFUNlY3VmpqSTVHcEJKZmZICm16MnJwMVVSQWdNQkFBRUNnZ0VBQXdSeWNNcng3dkNaK3JvVGROWkhGWk5k'
    'V2tkU1NYVy8ya2N3TThGNDBuWWIKd3llQUxqMUsvRXNGRW1XZElQeEozeXRpYWlXUnZSazN4aGxvdXBOTzVJZ0xT'
    'TE91WlM1eWxGT2JiUGVDM3AvRwpEbHFQeGxYUWdlR1daYjhaUUlXSHVPVWIreldYSEt1dzUzS1FsTHVtQzZ4Q0VU'
    'bmczV2JYM25tOGhpSUw2M05PCjFzRmNTOW40VlVKekJVeGRBM0pHL2piYU1sRjhvZitjYzB3ZGdRTXBsdSt6bDRU'
    'UzNUOGsrcThEc1NIeUs5WnEKamlrMkR3Zm1tNGhKWWV1Mi94Z0RqSWlOUDZkcTlLM2lnYnZNajdPTGNFTmxyd3JQ'
    'YlhIVjRwa25oUnV1KzhkagpueHB2aEpXZlZxMXN0eldCR0VyWUVIdllaTURmSmVkZWhKQmlTR2VKWVFLQmdRREsy'
    'ZmRjTkhqbmNQeDZpSjQwCm9kY095ZC9DRFdtY3poNWxjdjkrZEZIdVRVZjlwaXNkRnh0YkN4TDNoSGIzdC9MUUlz'
    'djlqbGZldklKN2dIa1QKQmxkbHBmY09VOFBoNnNDcmF2MkdNUVUwR3BYR002SWR1QW9vME1SdEk4WnpqUjVFMys0'
    'SVpDdnRjRGJKU1c3TQozT3VzNGk4bHJucFJ4cHBFWE1vUTJMTWd4d0tCZ1FDL1laL0dZaXZ2dVJNNm9ZTkl4dzhI'
    'djlhaElHWlBFQjZSCkRpTmh1aStEK3ZWYlVvRnFrRG02Q3lvbGZPVHpiM2cxeERWdjhleDM2ZGJPd2JZUU4ySExW'
    'bjBCaWRFS0gyU2YKSHlmbnNUcWpvbHhmM3ZJNDQyeUVNck1iS2dZNHIwKzlmWDVSOWJKeDhoOTVpVTM3aFkvZ1l2'
    'eC9XbzhGMzFvbApTNThrMFFhelp3S0JnRklzekhVdzJJM0JpclpFNC9va1djK20zaHRwZlpCRk83RVRUZ2MzTGYy'
    'Z2x2cGROM2Y0ClpWK1RjK0tMYWZwZUxXSTl4bTk0RzRhaXpTVWszV2RrbVVFWFk2Y05MZncyTWtqKzlhZEg4bml5'
    'RUZ5VGpDZ0gKNXkyenJPOGRvQVl0YzhhcEJHK256TmZLTHBlS1JQVit4WVpxdG5qSVhzc0Q3bmlsTWtKeTF0WC9B'
    'b0dBSHlRYgpnNFJsOGRRRHRQNmpCaXlkM1h6eHg3WWw3NmVIMGNLakx6dkVqNDArYjJXMWVVbU9teDlGOUdPbVBa'
    'WmQwU0hrCk1Cc0ZoMTJkZm5jMjBOeXlKUXdsdXlKWnlYUGlRNkltTkNVNmpYWFY0aU84OWxUTFM1ZVVYVTh4US9n'
    'QzJhcVoKNjJ3M1pTTW95L1h6b29IUkw0bnIzQzA0S0pSM2Jxb25jeTR3RVBFQ2dZRUFrYlRpdlVvVktuNVdSTTNu'
    'MGVnLwpNTGFIaklnNTVaNCt1ajM0OWlPTS9MbURHT3ozeGZYd25PZHpNN2I1aW9xbC8yM1RSbGp6MGRDZU9UVko1'
    'dzZmClhKcnNsM2Y2MHo0QitpdUtHUzJFSTRQL1pzRmFGOThIQU1EWitnV0Q0ZDFVa2JDL0RYMWFuUmRNSS95ajdB'
    'NEMKRE5LVCtUTS9DbXRIUlpxR3BBajltMG89Ci0tLS0tRU5EIFBSSVZBVEUgS0VZLS0tLS0K'
)

class CountingHTTPSServer(http.server.ThreadingHTTPServer):
    def __init__(self, server_address, RequestHandlerClass, ssl_context):
        super().__init__(server_address, RequestHandlerClass)
        self.ssl_context = ssl_context
        self.handshake_count = 0
        self.lock = threading.Lock()

    def get_request(self):
        sock, addr = super().get_request()
        # Wrap with SSL on incoming connection
        ssock = self.ssl_context.wrap_socket(sock, server_side=True)
        with self.lock:
            self.handshake_count += 1
        return ssock, addr

class TestHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        body = b"pong"
        if self.path == "/close":
            body = b"bye!"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass  # Quiet

def main():
    # Write cert and key
    cert_file = tempfile.NamedTemporaryFile(suffix=".pem", delete=False)
    cert_file.write(base64.b64decode(RSA_CERT_B64))
    cert_file.close()

    key_file = tempfile.NamedTemporaryFile(suffix=".pem", delete=False)
    key_file.write(base64.b64decode(RSA_KEY_B64))
    key_file.close()

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert_file.name, key_file.name)

    # Start Server 1
    server1 = CountingHTTPSServer(("127.0.0.1", 0), TestHandler, ctx)
    port1 = server1.server_address[1]
    t1 = threading.Thread(target=server1.serve_forever, daemon=True)
    t1.start()

    # Start Server 2 (for cross-target isolation test)
    server2 = CountingHTTPSServer(("127.0.0.1", 0), TestHandler, ctx)
    port2 = server2.server_address[1]
    t2 = threading.Thread(target=server2.serve_forever, daemon=True)
    t2.start()

    print(f"Server 1 running on 127.0.0.1:{port1}")
    print(f"Server 2 running on 127.0.0.1:{port2}")

    xu_client_src = f"""@main

http #net/http

pub fn main() {{
    $client := http.new_client()
    client.insecure_skip_verify = true

    // Request 1: GET to server 1
    u1 := "https://127.0.0.1:{port1}/keepalive"
    r1 := client.get(u1 + "") or (err) {{
        eprintln("r1 failed: " + err.msg())
        <<< 1
    }}
    if r1.status_code != 200 || r1.body != "pong" {{
        eprintln("r1 unexpected response: " + str(r1.status_code) + " " + r1.body)
        <<< 1
    }}
    if !client.has_idle_connection() {{
        eprintln("FAILED: client has no idle connection after r1")
        <<< 1
    }}
    println("OK: r1 succeeded, idle connection retained")

    // Request 2: GET to server 1 (should reuse connection)
    r2 := client.get(u1 + "") or (err) {{
        eprintln("r2 failed: " + err.msg())
        <<< 1
    }}
    if r2.status_code != 200 || r2.body != "pong" {{
        eprintln("r2 unexpected response: " + str(r2.status_code) + " " + r2.body)
        <<< 1
    }}
    if !client.has_idle_connection() {{
        eprintln("FAILED: client has no idle connection after r2")
        <<< 1
    }}
    println("OK: r2 succeeded with connection reuse")

    // Explicit cleanup
    client.close_idle_connections()
    if client.has_idle_connection() {{
        eprintln("FAILED: client still has idle connection after close_idle_connections")
        <<< 1
    }}
    println("OK: close_idle_connections cleared idle connection")

    // Request 3: GET to server 1 /close (server specifies Connection: close)
    u_close := "https://127.0.0.1:{port1}/close"
    r3 := client.get(u_close + "") or (err) {{
        eprintln("r3 failed: " + err.msg())
        <<< 1
    }}
    if r3.status_code != 200 || r3.body != "bye!" {{
        eprintln("r3 unexpected response: " + str(r3.status_code) + " " + r3.body)
        <<< 1
    }}
    if client.has_idle_connection() {{
        eprintln("FAILED: client retained idle connection after Connection: close")
        <<< 1
    }}
    println("OK: server Connection: close respected, idle pool not populated")

    // Request 4 & 5: Target isolation
    // Re-establish idle on server 1
    r4 := client.get(u1 + "") or (err) {{
        eprintln("r4 failed: " + err.msg())
        <<< 1
    }}
    if !client.has_idle_connection() {{
        eprintln("r4 failed to retain idle connection")
        <<< 1
    }}

    // Make request to server 2 (different port)
    u2 := "https://127.0.0.1:{port2}/keepalive"
    r5 := client.get(u2 + "") or (err) {{
        eprintln("r5 failed: " + err.msg())
        <<< 1
    }}
    if r5.status_code != 200 || r5.body != "pong" {{
        eprintln("r5 unexpected response: " + str(r5.status_code) + " " + r5.body)
        <<< 1
    }}
    println("OK: cross-target request succeeded")

    println("ALL_HTTPS_REUSE_TESTS_PASSED")
}}
"""
    tmp_src = tempfile.NamedTemporaryFile(suffix=".xu", delete=False)
    tmp_src.write(xu_client_src.encode("utf-8"))
    tmp_src.close()

    try:
        env = os.environ.copy()
        env["XU_STDLIB_ROOT"] = STDLIB_SRC
        env["XU_ROOT"] = XU_ROOT

        p = subprocess.run([COMPILER, "run", tmp_src.name], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        print("CLIENT STDOUT:\n" + p.stdout)
        if p.stderr:
            print("CLIENT STDERR:\n" + p.stderr)
        assert p.returncode == 0, f"Client failed with returncode {p.returncode}"
        assert "ALL_HTTPS_REUSE_TESTS_PASSED" in p.stdout

        # Verify server 1 handshakes:
        # Request 1: handshake 1
        # Request 2: reused (no handshake)
        # Request 3: handshake 2 (closed previously)
        # Request 4: handshake 3 (closed previously by /close)
        print(f"Server 1 total TLS handshakes: {server1.handshake_count}")
        print(f"Server 2 total TLS handshakes: {server2.handshake_count}")

        # r1 and r2 together did only 1 handshake on server 1!
        # Total handshakes on server 1 should be exactly 3 (for 4 requests: r1, r2, r3, r4)!
        assert server1.handshake_count == 3, f"Expected 3 handshakes on server 1, got {server1.handshake_count}"
        assert server2.handshake_count == 1, f"Expected 1 handshake on server 2, got {server2.handshake_count}"
        print("OK: TLS handshake counts exactly verified (r1 and r2 shared 1 handshake)!")
        print("SUCCESS: HTTPS connection reuse fully verified!")
    finally:
        server1.shutdown()
        server2.shutdown()
        os.remove(cert_file.name)
        os.remove(key_file.name)
        if os.path.exists(tmp_src.name):
            os.remove(tmp_src.name)

if __name__ == "__main__":
    main()
