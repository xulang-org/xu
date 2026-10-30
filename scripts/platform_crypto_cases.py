"""Public test-only crypto fixtures; generated with Python cryptography.

Certificates are valid 2020–2099. Keys are public test material, never credentials.
ECDSA scalars 1/2/3 identify root/intermediate/leaf; the pipe uses a test RSA key.
"""
import base64
from pathlib import Path

FIXTURES = {
    'root.der': (
        'MIIBbTCCAROgAwIBAgIBATAKBggqhkjOPQQDAjAXMRUwEwYDVQQDDAxYdSB0ZXN0IHJvb3QwIBcNMjAwMTAxMDAw'
        'MDAwWhgPMjA5OTAxMDEwMDAwMDBaMBcxFTATBgNVBAMMDFh1IHRlc3Qgcm9vdDBZMBMGByqGSM49AgEGCCqGSM49'
        'AwEHA0IABGsX0fLhLEJH+Lzm5WOkQPJ3A32BLeszoPShOUXYmMKWT+NC4v4af5uO5+tKfA+eFivOM1drMV7Oy7ZA'
        'aDe/UfWjTjBMMA8GA1UdEwEB/wQFMAMBAf8wDgYDVR0PAQH/BAQDAgGGMBQGA1UdEQQNMAuCCWxvY2FsaG9zdDAT'
        'BgNVHSUEDDAKBggrBgEFBQcDATAKBggqhkjOPQQDAgNIADBFAiBC+6BJaGHDqwg6+W44Fjr+zBZZyip1F5G82PS7'
        'j9fmUgIhAKUcPkHnUK8Q5wQdayxvFL0YQeQMi4ACn1urHMVgO3VS'
    ),
    'root.pem': (
        'LS0tLS1CRUdJTiBDRVJUSUZJQ0FURS0tLS0tCk1JSUJiVENDQVJPZ0F3SUJBZ0lCQVRBS0JnZ3Foa2pPUFFRREFq'
        'QVhNUlV3RXdZRFZRUUREQXhZZFNCMFpYTjAKSUhKdmIzUXdJQmNOTWpBd01UQXhNREF3TURBd1doZ1BNakE1T1RB'
        'eE1ERXdNREF3TURCYU1CY3hGVEFUQmdOVgpCQU1NREZoMUlIUmxjM1FnY205dmREQlpNQk1HQnlxR1NNNDlBZ0VH'
        'Q0NxR1NNNDlBd0VIQTBJQUJHc1gwZkxoCkxFSkgrTHptNVdPa1FQSjNBMzJCTGVzem9QU2hPVVhZbU1LV1QrTkM0'
        'djRhZjV1TzUrdEtmQStlRml2T00xZHIKTVY3T3k3WkFhRGUvVWZXalRqQk1NQThHQTFVZEV3RUIvd1FGTUFNQkFm'
        'OHdEZ1lEVlIwUEFRSC9CQVFEQWdHRwpNQlFHQTFVZEVRUU5NQXVDQ1d4dlkyRnNhRzl6ZERBVEJnTlZIU1VFRERB'
        'S0JnZ3JCZ0VGQlFjREFUQUtCZ2dxCmhrak9QUVFEQWdOSUFEQkZBaUJDKzZCSmFHSERxd2c2K1c0NEZqcit6Qlpa'
        'eWlwMUY1RzgyUFM3ajlmbVVnSWgKQUtVY1BrSG5VSzhRNXdRZGF5eHZGTDBZUWVRTWk0QUNuMXVySE1WZ08zVlMK'
        'LS0tLS1FTkQgQ0VSVElGSUNBVEUtLS0tLQo='
    ),
    'intermediate.der': (
        'MIIBdTCCARugAwIBAgIBAjAKBggqhkjOPQQDAjAXMRUwEwYDVQQDDAxYdSB0ZXN0IHJvb3QwIBcNMjAwMTAxMDAw'
        'MDAwWhgPMjA5OTAxMDEwMDAwMDBaMB8xHTAbBgNVBAMMFFh1IHRlc3QgaW50ZXJtZWRpYXRlMFkwEwYHKoZIzj0C'
        'AQYIKoZIzj0DAQcDQgAEfPJ7GI0DT36KUjgDBLUaw8CJaeJ38hs1pgtI/EdmmXgHd1UQ247QQCk9msafdDDbun2t'
        '5jzpgimeBLedInhz0aNOMEwwDwYDVR0TAQH/BAUwAwEB/zAOBgNVHQ8BAf8EBAMCAYYwFAYDVR0RBA0wC4IJbG9j'
        'YWxob3N0MBMGA1UdJQQMMAoGCCsGAQUFBwMBMAoGCCqGSM49BAMCA0gAMEUCIQC+4gDY0lfiQ4Xob9pjn3soynS1'
        'njEJ/+Ev2woIH/J33wIgE4YlJeLzUg2kPe4ds2fccG/Om99T3CUBNZnQyEP0PWg='
    ),
    'leaf.der': (
        'MIIBbjCCARWgAwIBAgIBAzAKBggqhkjOPQQDAjAfMR0wGwYDVQQDDBRYdSB0ZXN0IGludGVybWVkaWF0ZTAgFw0y'
        'MDAxMDEwMDAwMDBaGA8yMDk5MDEwMTAwMDAwMFowFDESMBAGA1UEAwwJbG9jYWxob3N0MFkwEwYHKoZIzj0CAQYI'
        'KoZIzj0DAQcDQgAEXsvk0aYzCkTI9++VHUvxZebGtyHvramF+0FmG8bn/WyHNGQMSZj/fjdLBs4aZKLs2CqwNjhP'
        'uD2aebEnon1QMqNLMEkwDAYDVR0TAQH/BAIwADAOBgNVHQ8BAf8EBAMCBaAwFAYDVR0RBA0wC4IJbG9jYWxob3N0'
        'MBMGA1UdJQQMMAoGCCsGAQUFBwMBMAoGCCqGSM49BAMCA0cAMEQCIDhp6eKHeLU6pVIBzdySnc3vUs4/DyN+Bi+0'
        'DehhXqzFAiBUeKua5/Pb/M+HtToKkSsYALpzUHI21JRr4f5G6BdTBg=='
    ),
    'rsa.pem': (
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
    ),
    'leaf-chain.pem': (
        'LS0tLS1CRUdJTiBDRVJUSUZJQ0FURS0tLS0tCk1JSUJiakNDQVJXZ0F3SUJBZ0lCQXpBS0JnZ3Foa2pPUFFRREFq'
        'QWZNUjB3R3dZRFZRUUREQlJZZFNCMFpYTjAKSUdsdWRHVnliV1ZrYVdGMFpUQWdGdzB5TURBeE1ERXdNREF3TURC'
        'YUdBOHlNRGs1TURFd01UQXdNREF3TUZvdwpGREVTTUJBR0ExVUVBd3dKYkc5allXeG9iM04wTUZrd0V3WUhLb1pJ'
        'emowQ0FRWUlLb1pJemowREFRY0RRZ0FFClhzdmswYVl6Q2tUSTkrK1ZIVXZ4WmViR3R5SHZyYW1GKzBGbUc4Ym4v'
        'V3lITkdRTVNaai9mamRMQnM0YVpLTHMKMkNxd05qaFB1RDJhZWJFbm9uMVFNcU5MTUVrd0RBWURWUjBUQVFIL0JB'
        'SXdBREFPQmdOVkhROEJBZjhFQkFNQwpCYUF3RkFZRFZSMFJCQTB3QzRJSmJHOWpZV3hvYjNOME1CTUdBMVVkSlFR'
        'TU1Bb0dDQ3NHQVFVRkJ3TUJNQW9HCkNDcUdTTTQ5QkFNQ0EwY0FNRVFDSURocDZlS0hlTFU2cFZJQnpkeVNuYzN2'
        'VXM0L0R5TitCaSswRGVoaFhxekYKQWlCVWVLdWE1L1BiL00rSHRUb0trU3NZQUxwelVISTIxSlJyNGY1RzZCZFRC'
        'Zz09Ci0tLS0tRU5EIENFUlRJRklDQVRFLS0tLS0KLS0tLS1CRUdJTiBDRVJUSUZJQ0FURS0tLS0tCk1JSUJkVEND'
        'QVJ1Z0F3SUJBZ0lCQWpBS0JnZ3Foa2pPUFFRREFqQVhNUlV3RXdZRFZRUUREQXhZZFNCMFpYTjAKSUhKdmIzUXdJ'
        'QmNOTWpBd01UQXhNREF3TURBd1doZ1BNakE1T1RBeE1ERXdNREF3TURCYU1COHhIVEFiQmdOVgpCQU1NRkZoMUlI'
        'UmxjM1FnYVc1MFpYSnRaV1JwWVhSbE1Ga3dFd1lIS29aSXpqMENBUVlJS29aSXpqMERBUWNEClFnQUVmUEo3R0kw'
        'RFQzNktVamdEQkxVYXc4Q0phZUozOGhzMXBndEkvRWRtbVhnSGQxVVEyNDdRUUNrOW1zYWYKZEREYnVuMnQ1anpw'
        'Z2ltZUJMZWRJbmh6MGFOT01Fd3dEd1lEVlIwVEFRSC9CQVV3QXdFQi96QU9CZ05WSFE4QgpBZjhFQkFNQ0FZWXdG'
        'QVlEVlIwUkJBMHdDNElKYkc5allXeG9iM04wTUJNR0ExVWRKUVFNTUFvR0NDc0dBUVVGCkJ3TUJNQW9HQ0NxR1NN'
        'NDlCQU1DQTBnQU1FVUNJUUMrNGdEWTBsZmlRNFhvYjlwam4zc295blMxbmpFSi8rRXYKMndvSUgvSjMzd0lnRTRZ'
        'bEplTHpVZzJrUGU0ZHMyZmNjRy9PbTk5VDNDVUJOWm5ReUVQMFBXZz0KLS0tLS1FTkQgQ0VSVElGSUNBVEUtLS0t'
        'LQo='
    ),
    'leaf-key.pem': (
        'LS0tLS1CRUdJTiBQUklWQVRFIEtFWS0tLS0tCk1JR0hBZ0VBTUJNR0J5cUdTTTQ5QWdFR0NDcUdTTTQ5QXdFSEJH'
        'MHdhd0lCQVFRZ0FBQUFBQUFBQUFBQUFBQUEKQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFPaFJBTkNBQVJleStU'
        'UnBqTUtSTWozNzVVZFMvRmw1c2EzSWUrdApxWVg3UVdZYnh1ZjliSWMwWkF4Sm1QOStOMHNHemhwa291ellLckEy'
        'T0UrNFBacDVzU2VpZlZBeQotLS0tLUVORCBQUklWQVRFIEtFWS0tLS0tCg=='
    ),
    'rsa-key.pem': (
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
    ),
    'ecdsa-public': (
        'BF7L5NGmMwpEyPfvlR1L8WXmxrch762phftBZhvG5/1shzRkDEmY/343SwbOGmSi7NgqsDY4T7g9mnmxJ6J9UDI='
    ),
    'ecdsa-signature': (
        'MEQCIEqzgaQfV+hX/is77dFMEtSUBlPKd4si0wpqDxygeXwUAiACSdPTvPCsMrTUeoD5t6e1NPTOCwDdAR4Vh4fz'
        'zYSqbg=='
    ),
}


def write_fixtures(directory: Path) -> None:
    for name, encoded in FIXTURES.items():
        (directory / name).write_bytes(base64.b64decode(encoded))


SOURCE = r'''@main
#os
#errors
#crypto/ecdsa
#crypto/sha256
#crypto/x509
#crypto/tls
#net
#time
fn bad_name(cert &x509.Certificate, roots &x509.CertPool, inter &x509.CertPool) bool {
    cert.verify_with_pools("wrong.invalid", time.now_time(), roots, inter) or (err) { << true }
    << false
}
fn crypto() int {
    public := os.read("ecdsa-public") or >>
    signature := os.read("ecdsa-signature") or >>
    digest := sha256.sum256_bytes("Xu independent ECDSA fixture")
    wrong := sha256.sum256_bytes("altered message")
    if !ecdsa.verify_asn1(&public, &digest, &signature) || ecdsa.verify_asn1(&public, &wrong, &signature) { << 2 }
    root := x509.parse_certificate(os.read("root.der") or >>) or >>
    intermediate := x509.parse_certificate(os.read("intermediate.der") or >>) or >>
    cert := x509.parse_certificate(os.read("leaf.der") or >>) or >>
    cert.check_signature_from(&intermediate) or >>
    intermediate.check_signature_from(&root) or >>
    $roots := x509.new_cert_pool()
    roots.add(root)
    $inter := x509.new_cert_pool()
    inter.add(intermediate)
    cert.verify_with_pools("localhost", time.now_time(), &roots, &inter) or >>
    if !bad_name(&cert, &roots, &inter) { << 3 }
    system := x509.system_cert_pool()
    if system.certs.len != 1 { << 4 }
    cert.verify_with_pools("localhost", time.now_time(), &system, &inter) or >>
    println("ECDSA and X509 chain/pool passed")
    << 0
}
fn pipe_serve(pc net.PipeConn, result chan int) {
    $config := tls.new_config("localhost")
    config.cert_pem = os.read("rsa.pem") or (err) { result <- -1
        << }
    config.key_pem = os.read("rsa-key.pem") or (err) { result <- -2
        << }
    $conn := tls.server_pipe(pc, &config) or (err) { eprintln(err.msg())
        result <- -3
        << }
    request := conn.read(4) or (err) { result <- -4
        << }
    if request != "ping" { result <- -5
        << }
    data := "pong"
    n := conn.write(&data) or (err) { result <- -6
        << }
    conn.close() or (err) { result <- -7
        << }
    result <- n
}
fn pipe_probe() int {
    pair := net.pipe()
    done := chan int{cap: 1}
    xu pipe_serve(pair.c1, done)
    $config := tls.new_config("localhost")
    pem := os.read("rsa.pem") or >>
    x509.append_certificates($&config.root_cas, &pem) or >>
    $conn := tls.client_pipe(pair.c2, &config) or >>
    data := "ping"
    if (conn.write(&data) or >>) != 4 { << 2 }
    reply := conn.read(4) or >>
    conn.close() or >>
    if reply != "pong" || <-done != 4 { << 3 }
    println("TLS pipe passed")
    << 0
}
fn interop(address string) int {
    $config := tls.new_config("localhost")
    pem := os.read("root.pem") or >>
    x509.append_certificates($&config.root_cas, &pem) or >>
    $conn := tls.dial("tcp4", address, &config) or >>
    state := conn.connection_state()
    if !state.handshake_complete || state.version != 771 || state.cipher_suite != 49195 { << 2 }
    data := "Xu stream probe"
    if (conn.write(&data) or >>) != data.len { << 3 }
    $reply := ""
    while reply.len < data.len {
        part := conn.read(128) or >>
        if part.len == 0 { << 4 }
        reply = reply + part
    }
    conn.close() or >>
    if reply != data { << 5 }
    println("TLS ECDHE interop passed")
    << 0
}
fn probe() int {
    a := args()
    if a[1] == "crypto" { << crypto() or >> }
    if a[1] == "pipe" { << pipe_probe() or >> }
    << interop(a[2] + "") or >>
}
fn main() int {
    << probe() or (err) { eprintln(err.msg())
        << 1 }
}
'''
