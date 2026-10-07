# STM32F407VG (Cortex-M4F, 168 MHz) image of the feeder IED, run under Renode.
CC = arm-none-eabi-gcc
SIZE = arm-none-eabi-size
FW = ../..
BUILD = build

ARCH = -mcpu=cortex-m4 -mthumb -mfloat-abi=hard -mfpu=fpv4-sp-d16
INCLUDES = -I. -I$(FW)/include -I$(FW)/src -I$(FW)/src/dsp -I$(FW)/src/prot -I$(FW)/src/pmu \
           -I$(FW)/src/rt -I$(FW)/src/ied -I$(FW)/testset
CFLAGS = $(ARCH) -std=c11 -O2 -g -Wall -Wextra -Werror -Wdouble-promotion -fno-common \
         -ffunction-sections -fdata-sections -MMD -MP $(INCLUDES)
# The legacy DNP3 encoder uses double for its analog scaling.
CFLAGS_DNP3 = $(filter-out -Wdouble-promotion,$(CFLAGS))
LDFLAGS = $(ARCH) -T stm32f407vg.ld --specs=nano.specs --specs=nosys.specs \
          -Wl,--gc-sections -Wl,-Map=$(BUILD)/ied.map -Wl,--print-memory-usage

IED_SRCS = $(addprefix $(FW)/, src/dsp/phasor.c src/dsp/symcomp.c src/dsp/sample_history.c \
           src/prot/oc_element.c src/prot/distance.c src/prot/breaker_failure.c \
           src/prot/freq_element.c src/prot/trip_matrix.c \
           src/pmu/timebase.c src/pmu/synchrophasor.c src/pmu/c37118.c \
           src/rt/sample_ring.c src/rt/cycle_stats.c \
           src/ied/event_recorder.c src/ied/ied_app.c testset/testset.c)
TARGET_SRCS = startup.c main.c
OBJS = $(addprefix $(BUILD)/, $(notdir $(IED_SRCS:.c=.o)) $(TARGET_SRCS:.c=.o) dnp3_outstation.o)

vpath %.c $(sort $(dir $(IED_SRCS))) .

.PHONY: all clean

all: $(BUILD)/ied.elf

$(BUILD):
	mkdir -p $(BUILD)

$(BUILD)/dnp3_outstation.o: $(FW)/src/dnp3_outstation.c | $(BUILD)
	$(CC) $(CFLAGS_DNP3) -c $< -o $@

$(BUILD)/%.o: %.c | $(BUILD)
	$(CC) $(CFLAGS) -c $< -o $@

$(BUILD)/ied.elf: $(OBJS) stm32f407vg.ld
	$(CC) $(LDFLAGS) $(OBJS) -o $@ -lm
	$(SIZE) $@

-include $(OBJS:.o=.d)

clean:
	rm -rf $(BUILD)
