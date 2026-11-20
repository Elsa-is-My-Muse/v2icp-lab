#ifndef V2ICP_BOUNDARY_H
#define V2ICP_BOUNDARY_H

#include <stdbool.h>
#include <stdint.h>

typedef enum {
    V2ICP_STAGE_OK = 0,
    V2ICP_STAGE_INVALID,
    V2ICP_STAGE_NOT_AUTHORIZED,
    V2ICP_STAGE_STALE,
    V2ICP_STAGE_BUSY,
    V2ICP_STAGE_NO_DATA
} v2icp_stage_result;

enum {
    V2ICP_HAS_DRIVEOFF = 1u << 0,
    V2ICP_HAS_PRECONDITION = 1u << 1,
    V2ICP_HAS_HVAC = 1u << 2,
    V2ICP_HAS_TEMPERATURE = 1u << 3,
    V2ICP_HAS_DISTANCE = 1u << 4,
    V2ICP_HAS_SOC = 1u << 5
};

typedef struct {
    int32_t driveoff_minutes;
    int32_t prec_dsrd;
    int32_t prec_hvac;
    int32_t ambienttemp_c;
    int32_t target_dist_raw;
    int32_t target_soc_percent;
} v2icp_target;

typedef struct {
    bool backend_authenticated;
    bool identity_matched;
    bool sequence_matched;
    bool fresh;
    bool local_policy_allows;
} v2icp_admission;

typedef struct {
    bool has_pending;
    uint32_t known_mask;
    v2icp_target pending;
} v2icp_target_slot;

v2icp_stage_result v2icp_stage_target(v2icp_target_slot *slot,
                                    const v2icp_target *target,
                                    const v2icp_admission *admission);
bool v2icp_take_target(v2icp_target_slot *slot, v2icp_target *target,
                      uint32_t *known_mask);

#endif
