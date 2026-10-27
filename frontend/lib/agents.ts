// The six agents as the panel shows them, and plain-words summaries of what they say (FE-4).

import type { TimelineItem } from "./api";

export const AGENTS: Record<string, { name: string; color: string; initial: string }> = {
  SALES: { name: "Sales", color: "#e9822e", initial: "S" },
  PLANNING: { name: "Planning", color: "#2f6fed", initial: "P" },
  INVENTORY: { name: "Inventory", color: "#15a37f", initial: "I" },
  PURCHASING: { name: "Purchasing", color: "#9b51e0", initial: "Pu" },
  WAREHOUSE: { name: "Warehouse", color: "#0f8bb5", initial: "W" },
  HR: { name: "HR", color: "#d6457a", initial: "H" },
  SIMULATOR_CLOCK: { name: "Clock", color: "#7c8798", initial: "⏱" },
};

export function agent(code: string | undefined) {
  return AGENTS[code ?? ""] ?? { name: code ?? "?", color: "#7c8798", initial: "?" };
}

const RESOURCE: Record<string, string> = {
  STOCK: "stock", SUPPLY: "supply", WORKFORCE: "worker-hours", STORAGE_SPACE: "storage space",
  RECEIVING_SLOT: "receiving slot", PRODUCTION_CAPACITY: "machine-hours",
};

/** Replace item ids (uuids) in a text by the item names the panel knows. */
export function readable(text: string, names: Record<string, string>): string {
  return text.replace(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi, (id) => names[id] ?? `#${id.slice(0, 6)}`);
}

/** "200 CHIP stock · by 2026-11-04" from negotiation terms. */
export function describeTerms(terms: Record<string, unknown> | null | undefined, names: Record<string, string> = {}): string {
  if (!terms) return "";
  const item = names[String(terms.resource_ref)] ? `${names[String(terms.resource_ref)]} ` : "";
  const what = item + (RESOURCE[String(terms.resource_type)] ?? String(terms.resource_type ?? ""));
  const unit = terms.unit === "h" ? " h" : "";
  const when = terms.available_from ?? terms.needed_by ?? terms.date_from;
  return `${terms.quantity ?? ""}${unit} ${what}${when ? ` · by ${when}` : ""}`.trim();
}

/** Short plain-words line for an event (the "published" notices in the conversation). */
export function describeEvent(item: TimelineItem): string {
  const p = item.payload ?? {};
  switch (item.type) {
    case "OrderConfirmed": return `Customer confirmed order ${p.order_number} (${p.quantity} by ${p.delivery_date})`;
    case "PlanCommitted": return `Plan committed: ${p.quantity} by ${p.delivery_day}`;
    case "PlanCommitFailed": return `Plan could not be committed (${p.reason})`;
    case "PlanRevised": return `Plan revised: ${String(p.reason ?? "").toLowerCase().replaceAll("_", " ")}`;
    case "PlanAtRisk": return `Order at risk: ${String(p.reason ?? "").toLowerCase().replaceAll("_", " ")}`;
    case "ProductionOrderReleased": return `Production order released (${p.quantity})`;
    case "ProductionStarted": return `Production started (${p.quantity})`;
    case "ProductionBatchCompleted": return `Batch done: ${p.completed} of ${p.total} at ${String(p.hour).padStart(2, "0")}:00`;
    case "ProductionCompleted": return `Production completed (${p.quantity})`;
    case "MaterialIssuedToProduction": return `Kits issued to production (${p.kits} kits)`;
    case "FinishedGoodsStored": return `Goods stored in ${String(p.zone ?? "").toLowerCase().replaceAll("_", " ")} (${p.quantity})`;
    case "ShipmentDispatched": return `Shipment dispatched (${p.quantity})`;
    case "ReservationCommitted": return `Stock reserved (${p.quantity})`;
    case "ReservationReleased": return `Reservation released (${p.quantity})`;
    case "WorkforceCommitted": return `Worker-hours committed (${p.skill})`;
    case "WorkforceCapacityChanged": return `Workforce changed: ${p.worker} absent`;
    case "ProcurementCommitted": return `Purchase committed with the supplier`;
    case "MaterialReceived": return `Delivery received (${p.quantity})`;
    case "SupplierDeliveryDelayed": return `Supplier delay: ${p.old_date} → ${p.new_date}`;
    case "ReceivingSlotCommitted": return `Receiving slot booked: ${p.quantity} on ${p.arrival_day}`;
    case "StorageCapacityChanged": return `Capacity changed: ${String(p.resource ?? "").toLowerCase().replaceAll("_", " ")} → ${p.units}`;
    case "SafetyStockBreached": return `Safety stock used (${p.released})`;
    case "SimulatedDayStarted": return `New day: ${p.date}`;
    default: return item.type ?? "";
  }
}
