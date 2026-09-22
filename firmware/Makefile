CC ?= gcc
CFLAGS ?= -std=c11 -Wall -Wextra -Werror -Iinclude -Isrc -Itests
COVFLAGS = --coverage -O0 -g
BUILD = build

SRCS = src/fault_detect.c src/recloser.c src/dnp3_outstation.c
TEST_SRCS = $(wildcard tests/test_*.c)
TEST_BINS = $(patsubst tests/%.c,$(BUILD)/%,$(TEST_SRCS))

.PHONY: all test coverage clean

all: $(BUILD)/relay_app.o

$(BUILD)/relay_app.o: $(SRCS) | $(BUILD)
	$(CC) $(CFLAGS) -c src/fault_detect.c -o $(BUILD)/fault_detect.o
	$(CC) $(CFLAGS) -c src/recloser.c -o $(BUILD)/recloser.o
	$(CC) $(CFLAGS) -c src/dnp3_outstation.c -o $(BUILD)/dnp3_outstation.o
	$(LD) -r $(BUILD)/fault_detect.o $(BUILD)/recloser.o $(BUILD)/dnp3_outstation.o -o $@

$(BUILD):
	mkdir -p $(BUILD)

$(BUILD)/%: tests/%.c $(SRCS) | $(BUILD)
	$(CC) $(CFLAGS) $(COVFLAGS) $< $(SRCS) -o $@ -lm

test: $(TEST_BINS)
	@set -e; for t in $(TEST_BINS); do echo "== $$t"; $$t; done

coverage: test
	@cd $(BUILD) && gcov -i -o . *.gcda > /dev/null 2>&1 || true
	@echo "gcov json written to $(BUILD)"

clean:
	rm -rf $(BUILD)
