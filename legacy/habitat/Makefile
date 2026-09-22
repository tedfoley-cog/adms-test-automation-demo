# Off-line build of the RTNET batch tasks. On the platform these are built by
# the HDB codeset tooling against HABITAT_SRCDIR; here they are compiled
# standalone so a savecase export can be replayed without a clone context.

FC      ?= gfortran
FFLAGS  ?= -std=f2008 -ffree-form -Wall -O2 -J build
BUILD    = build
SAVECASE = savecases/rtnet_ems_0742.export

all: $(BUILD)/rtgenace $(BUILD)/loadshed

$(BUILD):
	@mkdir -p $(BUILD)

$(BUILD)/hab_savecase.o: src/hab_savecase.f90 | $(BUILD)
	$(FC) $(FFLAGS) -c $< -o $@

$(BUILD)/rtgenace: src/ace_calc.f90 $(BUILD)/hab_savecase.o
	$(FC) $(FFLAGS) -I$(BUILD) $^ -o $@

$(BUILD)/loadshed: src/loadshed.f90 $(BUILD)/hab_savecase.o
	$(FC) $(FFLAGS) -I$(BUILD) $^ -o $@

replay: all
	@$(BUILD)/rtgenace $(SAVECASE)
	@$(BUILD)/loadshed $(SAVECASE)

clean:
	rm -rf $(BUILD)

.PHONY: all replay clean
