#include "v2icp_boundary.h"

#include <assert.h>
#include <stdio.h>

int main(void)
{
    v2icp_target_slot slot = {0};
    v2icp_target candidate = {60, 1, 3, 18, 120, 80};
    v2icp_target accepted = {0};
    v2icp_admission admission = {true, true, true, true, true};
    uint32_t mask = 0;

    assert(v2icp_stage_target(0, &candidate, &admission) == V2ICP_STAGE_INVALID);
    admission.local_policy_allows = false;
    assert(v2icp_stage_target(&slot, &candidate, &admission) == V2ICP_STAGE_NOT_AUTHORIZED);
    assert(!slot.has_pending);
    admission.local_policy_allows = true;
    admission.fresh = false;
    assert(v2icp_stage_target(&slot, &candidate, &admission) == V2ICP_STAGE_STALE);
    admission.fresh = true;
    candidate.target_soc_percent = 101;
    assert(v2icp_stage_target(&slot, &candidate, &admission) == V2ICP_STAGE_INVALID);
    candidate.target_soc_percent = 90;
    assert(v2icp_stage_target(&slot, &candidate, &admission) == V2ICP_STAGE_OK);
    assert(v2icp_stage_target(&slot, &candidate, &admission) == V2ICP_STAGE_BUSY);
    assert(v2icp_take_target(&slot, &accepted, &mask));
    assert(accepted.target_soc_percent == 90 && (mask & V2ICP_HAS_SOC));
    assert(!v2icp_take_target(&slot, &accepted, &mask));
    candidate = (v2icp_target){-1, -1, -1, -51, -1, -1};
    assert(v2icp_stage_target(&slot, &candidate, &admission) == V2ICP_STAGE_NO_DATA);
    candidate.ambienttemp_c = -1;
    assert(v2icp_stage_target(&slot, &candidate, &admission) == V2ICP_STAGE_OK);
    assert(v2icp_take_target(&slot, &accepted, &mask));
    assert(mask == V2ICP_HAS_TEMPERATURE && accepted.ambienttemp_c == -1);
    puts("PASS: host-only admission boundary; no MCU, CAN or actuator was accessed.");
    return 0;
}
