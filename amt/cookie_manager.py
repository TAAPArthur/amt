

def load_cookies(file_like, session):
    for line in file_like:
        line = line.strip()
        if not line or line[0] == "#":
            if line.startswith("#HttpOnly_"):
                line = line[len("#HttpOnly_"):]
            else:
                continue
        domain, domain_specified, path, secure, expires, name, value, _ = \
            (line + "\t").split("\t", 7)
        session.cookies.set(name, value, path=path, domain=domain, secure=secure == "TRUE", expires=expires if expires else None)
