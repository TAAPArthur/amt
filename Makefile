APP_NAME := amt

test:
	coverage run --source=amt -m unittest --buffer $(TEST_ARGS)

debug:
	DEBUG=1 coverage run --source=amt -m unittest --buffer -f -v $(TEST_ARGS)

inspect:
	DEBUG=1 coverage run --source=amt -m unittest -v $(TEST_ARGS)

quick-test:
	QUICK=1 coverage run --source=amt -m unittest --buffer $(TEST_ARGS)

coverage:
	coverage html

install:
	install -m 0744 -Dt "$(DESTDIR)/usr/lib/python3.9/$(APP_NAME)" $(APP_NAME)/*.py
	install -m 0744 -Dt "$(DESTDIR)/usr/lib/python3.9/$(APP_NAME)/servers" $(APP_NAME)/servers/*.py
	install -m 0744 -Dt "$(DESTDIR)/usr/lib/python3.9/$(APP_NAME)/trackers" $(APP_NAME)/trackers/*.py
	install -D -m 0755 main.py "$(DESTDIR)/usr/bin/amt"
uninstall:
	rm -rdf "$(DESTDIR)/usr/lib/python3.9/site-packages/$(APP_NAME)"
	rm -f "$(DESTDIR)/usr/bin/amt"
