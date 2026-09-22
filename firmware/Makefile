CC ?= gcc
CFLAGS ?= -std=c11 -Wall -Wextra -Werror -Iinclude -Isrc -Itests
COVFLAGS = --coverage -O0 -g
BUILD = build

SRCS = src/fault_detect.c src/recloser.c src/dnp3_outstation.c
TEST_SRCS = $(wildcard tests/test_*.c)
TEST_BINS = $(patsubst tests/%.c,$(BUILD)/%,$(TEST_SRCS))
TEST_PROFILE_DIRS = $(patsubst tests/%.c,$(BUILD)/%.p,$(TEST_SRCS))

.PHONY: all test coverage clean prune

all: $(BUILD)/relay_app.o

$(BUILD)/relay_app.o: $(SRCS) | $(BUILD)
	$(CC) $(CFLAGS) -c src/fault_detect.c -o $(BUILD)/fault_detect.o
	$(CC) $(CFLAGS) -c src/recloser.c -o $(BUILD)/recloser.o
	$(CC) $(CFLAGS) -c src/dnp3_outstation.c -o $(BUILD)/dnp3_outstation.o
	$(LD) -r $(BUILD)/fault_detect.o $(BUILD)/recloser.o $(BUILD)/dnp3_outstation.o -o $@

$(BUILD):
	mkdir -p $(BUILD)

# Each test links its own copy of the sources into a private object/profile
# directory, so the .gcno/.gcda pair of one test binary never collides with
# another's.
$(BUILD)/%: tests/%.c $(SRCS) | $(BUILD)
	@mkdir -p $(BUILD)/$*.p
	@rm -f $(BUILD)/$*.p/*.gcda $(BUILD)/$*.p/*.gcov.json.gz
	$(CC) $(CFLAGS) $(COVFLAGS) -c $< -o $(BUILD)/$*.p/$*.o
	@set -e; for s in $(SRCS); do \
		$(CC) $(CFLAGS) $(COVFLAGS) -c $$s -o $(BUILD)/$*.p/`basename $$s .c`.o; \
	done
	$(CC) $(COVFLAGS) $(BUILD)/$*.p/*.o -o $@ -lm

# A renamed or deleted test leaves its object/profile directory behind, and
# gcov would keep crediting those stale .gcda files to the coverage report.
prune:
	@rm -f $(BUILD)/*.gcda $(BUILD)/*.gcno $(BUILD)/*.gcov.json.gz
	@for d in $(BUILD)/*.p; do \
		[ -e "$$d" ] || continue; \
		case " $(TEST_PROFILE_DIRS) " in \
			*" $$d "*) ;; \
			*) echo "pruning stale profile dir $$d"; rm -rf "$$d" "$${d%.p}" ;; \
		esac; \
	done

test: prune $(TEST_BINS)
	@set -e; for t in $(TEST_BINS); do echo "== $$t"; $$t; done

coverage: test
	@set -e; for d in $(BUILD)/*.p; do \
		(cd $$d && gcov -i -o . *.gcda > /dev/null 2>&1 || true); \
	done
	@echo "gcov json written to $(BUILD)"

clean:
	rm -rf $(BUILD)
