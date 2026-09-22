/* Minimal assertion harness used by the relay unit tests.
 * Kept dependency-free so it builds on the target toolchain as well as host gcc. */
#ifndef TEST_HARNESS_H
#define TEST_HARNESS_H

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int th_tests_run = 0;
static int th_tests_failed = 0;
static const char *th_current_case = "";

#define TH_CASE(name)                                                                   \
    do {                                                                                \
        th_current_case = (name);                                                       \
        th_tests_run++;                                                                 \
    } while (0)

#define TH_ASSERT(cond)                                                                 \
    do {                                                                                \
        if (!(cond)) {                                                                  \
            th_tests_failed++;                                                          \
            printf("FAIL %s: %s (%s:%d)\n", th_current_case, #cond, __FILE__, __LINE__); \
        }                                                                               \
    } while (0)

#define TH_ASSERT_NEAR(actual, expected, tol)                                           \
    do {                                                                                \
        double th_a = (actual);                                                         \
        double th_e = (expected);                                                       \
        if (fabs(th_a - th_e) > (tol)) {                                                \
            th_tests_failed++;                                                          \
            printf("FAIL %s: expected %.6f got %.6f (%s:%d)\n", th_current_case, th_e,  \
                   th_a, __FILE__, __LINE__);                                           \
        }                                                                               \
    } while (0)

static int th_report(const char *suite)
{
    printf("%s: %d cases, %d failed\n", suite, th_tests_run, th_tests_failed);
    return th_tests_failed == 0 ? 0 : 1;
}

#endif /* TEST_HARNESS_H */
