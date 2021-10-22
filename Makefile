APP_NAME := amt

test:
	coverage run --source=amt -m unittest --buffer $(TEST_ARGS)

debug:
	coverage run --source=amt -m unittest --buffer -f -v $(TEST_ARGS)

inspect:
	coverage run --source=amt -m unittest -v $(TEST_ARGS)

quick_test_coverage: export QUICK=1
quick_test_coverage: test
	coverage report --omit "*test*,amt/server*,amt/trackers*,amt/util/decoder.py" --fail-under=100 --skip-empty -m
	coverage report --include amt/servers/local.py,amt/servers/remote.py --fail-under=100 --skip-empty -m

full_test_coverage: test
	coverage report --omit "*test*,amt/trackers/*,$$(grep login -l amt/servers/*.py | sed -z 's/\n/,/g')" --fail-under=100 --skip-empty -m
	coverage report --omit "*test*" --fail-under=95 --skip-empty

coverage_html:
	coverage html

install:
	python setup.py install "--root=$(DESTDIR)/"
	install -D -m 0755 main.py "$(DESTDIR)/usr/bin/$(APP_NAME)"

uninstall:
	rm -rdf "$(DESTDIR)"/usr/lib/python*/site-packages/"$(APP_NAME)"
	rm -f "$(DESTDIR)/usr/bin/$(APP_NAME)"
