CC ?= gcc
CFLAGS ?= -std=c11 -Wall -Wextra -Werror -Iinclude -Isrc -Itests
COVFLAGS = --coverage -O0 -g
BUILD = build

SRCS = src/fault_detect.c src/recloser.c src/dnp3_outstation.c
TEST_SRCS = $(wildcard tests/test_*.c)
TEST_BINS = $(patsubst tests/%.c,$(BUILD)/%,$(TEST_SRCS))
TEST_OBJDIRS = $(patsubst tests/%.c,$(BUILD)/%.obj,$(TEST_SRCS))

.PHONY: all test coverage prune clean

all: $(BUILD)/relay_app.o

$(BUILD)/relay_app.o: $(SRCS) | $(BUILD)
	$(CC) $(CFLAGS) -c src/fault_detect.c -o $(BUILD)/fault_detect.o
	$(CC) $(CFLAGS) -c src/recloser.c -o $(BUILD)/recloser.o
	$(CC) $(CFLAGS) -c src/dnp3_outstation.c -o $(BUILD)/dnp3_outstation.o
	$(LD) -r $(BUILD)/fault_detect.o $(BUILD)/recloser.o $(BUILD)/dnp3_outstation.o -o $@

$(BUILD):
	mkdir -p $(BUILD)

# Each test binary keeps its objects (and therefore its .gcda profiles) in its
# own directory: the sources are linked into every binary, so a shared profile
# directory makes the runs overwrite each other's counters.
$(BUILD)/%: tests/%.c $(SRCS) | $(BUILD)
	@mkdir -p $(BUILD)/$*.obj
	$(CC) $(CFLAGS) $(COVFLAGS) -c $< -o $(BUILD)/$*.obj/$*.o
	@set -e; for s in $(SRCS); do \
		$(CC) $(CFLAGS) $(COVFLAGS) -c $$s -o $(BUILD)/$*.obj/`basename $$s .c`.o; \
	done
	$(CC) $(COVFLAGS) $(BUILD)/$*.obj/*.o -o $@ -lm

# A deleted test leaves its object directory (and its .gcda) behind, which
# would keep crediting the coverage report with lines nothing exercises.
prune:
	@set -e; for d in $(BUILD)/*.obj; do \
		[ -d "$$d" ] || continue; \
		case " $(TEST_OBJDIRS) " in *" $$d "*) ;; *) rm -rf "$$d";; esac; \
	done

test: prune $(TEST_BINS)
	@set -e; for t in $(TEST_BINS); do echo "== $$t"; $$t; done

coverage: test
	@set -e; for d in $(BUILD)/*.obj; do (cd $$d && gcov -i -o . *.gcda > /dev/null 2>&1 || true); done
	@echo "gcov json written to $(BUILD)/*.obj"

clean:
	rm -rf $(BUILD)
