APP_NAME := amt

all: quick_test

test_coverage:
	coverage run --source=amt -m unittest --buffer $(TEST_ARGS)

test:
	python -m unittest --buffer $(TEST_ARGS)

debug:
	python -m unittest --buffer -f -v $(TEST_ARGS)

inspect:
	python -m unittest -v -f $(TEST_ARGS)


quick_test: export QUICK=1
quick_test: test

quick_test_coverage: export QUICK=1
quick_test_coverage: test_coverage
	coverage report --omit "*test*,amt/server.py,amt/servers/*,amt/trackers/*,amt/util/decoder.py" --fail-under=100 --skip-empty -m
	coverage report --include amt/servers/local.py,amt/servers/remote.py --fail-under=100 --skip-empty -m

full_test_coverage: test_coverage
	coverage report --omit "*test*,amt/trackers/*,$$(grep -l login amt/servers/*.py | tr '\n' ',')" --fail-under=99 --skip-empty -m
	coverage report --omit "*test*" --fail-under=90 --skip-empty -m

coverage_html:
	coverage html

install:
	python setup.py install "--root=$(DESTDIR)/"
