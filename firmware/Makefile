CC ?= gcc
INCLUDES = -Iinclude -Isrc -Isrc/dsp -Isrc/prot -Isrc/pmu -Isrc/rt -Isrc/ied -Itestset -Itests
CFLAGS ?= -std=c11 -Wall -Wextra -Werror $(INCLUDES)
COVFLAGS = --coverage -O0 -g
BUILD = build

FEEDER_SRCS = src/fault_detect.c src/recloser.c src/dnp3_outstation.c
IED_SRCS = src/dsp/phasor.c src/dsp/symcomp.c src/dsp/sample_history.c \
           src/prot/oc_element.c src/prot/distance.c src/prot/breaker_failure.c \
           src/prot/freq_element.c src/prot/trip_matrix.c \
           src/pmu/timebase.c src/pmu/synchrophasor.c src/pmu/c37118.c \
           src/rt/sample_ring.c src/rt/cycle_stats.c \
           src/ied/event_recorder.c src/ied/ied_app.c
SRCS = $(FEEDER_SRCS) $(IED_SRCS)
HOST_SRCS = sim/host_rt.c testset/testset.c
HDRS = $(wildcard include/*.h src/*.h src/*/*.h testset/*.h tests/*.h)
TEST_SRCS = $(wildcard tests/test_*.c)
TEST_BINS = $(patsubst tests/%.c,$(BUILD)/%,$(TEST_SRCS))

.PHONY: all test coverage sim target clean

all: $(BUILD)/relay_app.o

$(BUILD)/relay_app.o: $(SRCS) $(HDRS) | $(BUILD)
	$(CC) $(CFLAGS) -r $(SRCS) -o $@

$(BUILD):
	mkdir -p $(BUILD)

$(BUILD)/%: tests/%.c $(SRCS) $(HOST_SRCS) $(HDRS) | $(BUILD)
	$(CC) $(CFLAGS) $(COVFLAGS) $< $(SRCS) $(HOST_SRCS) -o $@ -lm

test: $(TEST_BINS)
	@rm -f $(BUILD)/*.gcda $(BUILD)/*.gcov.json.gz
	@set -e; for t in $(TEST_BINS); do echo "== $$t"; $$t; done

coverage: test
	@cd $(BUILD) && gcov -i -o . *.gcda > /dev/null 2>&1 || true
	@echo "gcov json written to $(BUILD)"

# Host closed-loop simulator and PMU compliance harness.
sim: $(BUILD)/ied_sim $(BUILD)/pmu_compliance

$(BUILD)/ied_sim: sim/ied_sim.c $(SRCS) $(HOST_SRCS) $(HDRS) | $(BUILD)
	$(CC) $(CFLAGS) -O2 sim/ied_sim.c $(SRCS) $(HOST_SRCS) -o $@ -lm

$(BUILD)/pmu_compliance: sim/pmu_compliance.c $(SRCS) $(HOST_SRCS) $(HDRS) | $(BUILD)
	$(CC) $(CFLAGS) -O2 sim/pmu_compliance.c $(SRCS) $(HOST_SRCS) -o $@ -lm

# STM32F407 (Cortex-M4F) image for Renode; see target/stm32f407/Makefile.
target:
	$(MAKE) -C target/stm32f407

clean:
	rm -rf $(BUILD)
	$(MAKE) -C target/stm32f407 clean
