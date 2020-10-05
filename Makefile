APP_NAME := amt

test:
	coverage run --source=amt -m unittest -f

install:
	install -m 0744 -Dt "$(DESTDIR)/usr/lib/python3.8/site-packages/$(APP_NAME)" $(APP_NAME)/*.py
	install -m 0744 -Dt "$(DESTDIR)/usr/lib/python3.8/site-packages/$(APP_NAME)/servers" $(APP_NAME)/servers/*.py
	install -m 0744 -Dt "$(DESTDIR)/usr/lib/python3.8/site-packages/$(APP_NAME)/trackers" $(APP_NAME)/trackers/*.py
	install -D -m 0755 main.py "$(DESTDIR)/usr/bin/amt"
uninstall:
	rm -rdf "$(DESTDIR)/usr/lib/python3.8/site-packages/$(APP_NAME)"
	rm -f "$(DESTDIR)/usr/bin/amt"
