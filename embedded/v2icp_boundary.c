#include "v2icp_boundary.h"

static bool in_range_or_sna(int32_t value, int32_t minimum, int32_t maximum,
                            int32_t sna)
{
    return value == sna || (value >= minimum && value <= maximum);
}

v2icp_stage_result v2icp_stage_target(v2icp_target_slot *slot,
                                    const v2icp_target *target,
                                    const v2icp_admission *admission)
{
    uint32_t mask = 0;
    if (slot == 0 || target == 0 || admission == 0) {
        return V2ICP_STAGE_INVALID;
    }
    if (!admission->backend_authenticated || !admission->identity_matched ||
        !admission->sequence_matched || !admission->local_policy_allows) {
        return V2ICP_STAGE_NOT_AUTHORIZED;
    }
    if (!admission->fresh) {
        return V2ICP_STAGE_STALE;
    }
    if (!in_range_or_sna(target->driveoff_minutes, 0, 1440, -1) ||
        !in_range_or_sna(target->prec_dsrd, 0, 1, -1) ||
        !in_range_or_sna(target->prec_hvac, 0, 3, -1) ||
        !in_range_or_sna(target->ambienttemp_c, -50, 70, -51) ||
        !in_range_or_sna(target->target_dist_raw, 0, 1000, -1) ||
        !in_range_or_sna(target->target_soc_percent, 0, 100, -1)) {
        return V2ICP_STAGE_INVALID;
    }
    if (slot->has_pending) {
        return V2ICP_STAGE_BUSY;
    }
    if (target->driveoff_minutes != -1) mask |= V2ICP_HAS_DRIVEOFF;
    if (target->prec_dsrd != -1) mask |= V2ICP_HAS_PRECONDITION;
    if (target->prec_hvac != -1) mask |= V2ICP_HAS_HVAC;
    if (target->ambienttemp_c != -51) mask |= V2ICP_HAS_TEMPERATURE;
    if (target->target_dist_raw != -1) mask |= V2ICP_HAS_DISTANCE;
    if (target->target_soc_percent != -1) mask |= V2ICP_HAS_SOC;
    if (mask == 0) {
        return V2ICP_STAGE_NO_DATA;
    }
    slot->pending = *target;
    slot->known_mask = mask;
    slot->has_pending = true;
    return V2ICP_STAGE_OK;
}

bool v2icp_take_target(v2icp_target_slot *slot, v2icp_target *target,
                      uint32_t *known_mask)
{
    if (slot == 0 || target == 0 || known_mask == 0 || !slot->has_pending) {
        return false;
    }
    *target = slot->pending;
    *known_mask = slot->known_mask;
    slot->has_pending = false;
    slot->known_mask = 0;
    return true;
}
