//! Slot extraction

use std::collections::HashMap;

/// Extract slots from text based on command definition
pub fn extract_slots(
    text: &str,
    phrase: &str,
    slot_defs: &HashMap<String, crate::commands::SlotDef>,
) -> HashMap<String, String> {
    let mut slots = HashMap::new();

    if slot_defs.is_empty() {
        return slots;
    }

    // Simple extraction: remove phrase from text, assign remaining to first slot
    let remaining = text.replace(phrase, "").trim().to_string();

    if !remaining.is_empty() {
        if let Some((slot_name, _)) = slot_defs.iter().next() {
            slots.insert(slot_name.clone(), remaining);
        }
    }

    slots
}
