import type { components } from "@/types/api";

type VehicleUpdate = components["schemas"]["PlanVehicleUpdate"];
type Plan = components["schemas"]["TransportPlanOut"];

/** Cập nhật xe trên kế hoạch nội bộ, giữ trạng thái chờ đồng bộ TMS. */
export async function updatePlanVehicle(planId: string, data: VehicleUpdate): Promise<Plan> {
  const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/plans/${planId}/vehicle`, {
    method: "PATCH",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(typeof error.detail === "string" ? error.detail : "Không thể cập nhật kế hoạch.");
  }
  return response.json();
}
