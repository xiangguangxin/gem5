/* Teaching workload: volatile reads prevent removal of the measured accesses.
 * Full-program gem5 statistics include initialization and printing; no ROI here.
 */
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>

#ifndef WORKSET_BYTES
#define WORKSET_BYTES (64 * 1024)
#endif
#ifndef ROUNDS
#define ROUNDS 16
#endif

_Static_assert(WORKSET_BYTES >= 8 && WORKSET_BYTES % 8 == 0,
               "WORKSET_BYTES must be a positive multiple of eight");
_Static_assert(ROUNDS > 0, "ROUNDS must be positive");

static volatile uint64_t data[WORKSET_BYTES / sizeof(uint64_t)];

int main(void)
{
    const size_t count = sizeof(data) / sizeof(data[0]);
    uint64_t sum = 0;
    for (size_t i = 0; i < count; ++i)
        data[i] = i;
    for (unsigned r = 0; r < ROUNDS; ++r)
        for (size_t i = 0; i < count; ++i)
            sum += data[i];
    const uint64_t expected = (uint64_t)ROUNDS * count * (count - 1) / 2;
    printf("workset_bytes=%zu rounds=%u checksum=%" PRIu64
           " expected=%" PRIu64 "\n",
           sizeof(data), (unsigned)ROUNDS, sum, expected);
    return sum == expected ? 0 : 1;
}
