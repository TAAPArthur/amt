APP_NAME := amt

COVERAGE_DIR = coverage_dir

all: quick_test

test_coverage:
	rm -f ./$(COVERAGE_DIR)/*.cover
	python -m trace -c -m -s -C $$PWD/$(COVERAGE_DIR) --ignore-dir=/usr/lib --module unittest --buffer $(TEST_ARGS)

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
	! grep -n ">>>" $(COVERAGE_DIR)/* | grep -v " pragma: no cover" | grep -v -e "amt.server" -e "amt.tracker" -e amt.tests.test.cover
	! grep -n ">>>" $(COVERAGE_DIR)/* | grep -v " pragma: no cover" | grep -e amt.servers.local -e amt.servers.remote -e amt.servers.torrent

full_test_coverage: test_coverage
	! grep -n ">>>" $(COVERAGE_DIR)/* | grep -v " pragma: no cover" | grep -v -e "amt.servers.crunchyroll" -e "amt.servers.hidive" -e  $$(grep -l login amt/servers/*.py | tr '\n' ',' | sed "s/,/ -e /g")

coverage_html:
	coverage html

install:
	python setup.py install "--root=$(DESTDIR)/"
	install -Dt $(DESTDIR)/usr/share/amt scripts/*

clean:
	find ./$(COVERAGE_DIR)/*. -name "*.cover" -exec rm {} \+
