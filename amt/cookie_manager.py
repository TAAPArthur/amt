from selenium.webdriver import Firefox
from selenium.webdriver.firefox.options import Options


def get_driver():
    options = Options()
    options.add_argument("--headless")
    return Firefox(service_log_path="/dev/null", options=options)


def get_cookies(driver, url):
    driver.get(url)
    cookies = driver.get_cookies()

    for cookie in cookies:
        if cookie["name"] and cookie["value"]:
            # print(cookie)
            domain = cookie["domain"]
            if cookie["domain"].startswith(".www"):
                cookie["domain"][4:]
            if cookie["domain"].startswith("www"):
                cookie["domain"][3:]
            l = [domain, "TRUE", cookie["path"], str(cookie["secure"]).upper(), str(cookie.get("expiry", "")), cookie["name"], cookie["value"]]
            assert len(l) == 7
            yield "\t".join(l)


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


def update_session(url, session):
    with get_driver() as driver:
        cookies = list(get_cookies(driver, url))
    load_cookies(cookies, session)
    with open("/tmp/cookies.txt", "w") as f:
        for line in cookies:
            f.write(line + "\n")
