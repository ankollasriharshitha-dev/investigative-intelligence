# Internal Schema Registry

The current normalized package is the canonical MVP contract. Providers may use files, a database, or an API, but services consume the same snapshot shape.

## Entities

| Entity | Stable ID | Required fields |
| --- | --- | --- |
| PERSON | `person_id` | `name`, `role`, `case_ids` |
| PHONE | `phone_id` | `phone_number`, `owner_person_id`, `case_id` |
| LOCATION | `location_id` | `label`, `latitude`, `longitude` |
| VEHICLE | `vehicle_id` | `registration_number`, `owner_person_id`, `case_id` |
| ORGANIZATION | `organization_id` | `name`, `sector`, `case_ids` |
| ACCOUNT | `account_id` | `account_label`, `owner_person_id`, `organization_id`, `case_id` |
| CASE | `case_id` | `title`, `status`, `priority`, `opened_date` |
| EVENT | `event_id` | `person_id`, `event_type`, `timestamp`, `case_id` |

## Relationships

Relationship records retain stable record IDs plus `source`, `timestamp`, `case_id`, and `confidence` where available.

- Calls: `caller_id` -> `receiver_id`, relationship `CALLED`
- Messages: `sender_phone_id` -> `receiver_phone_id`, relationship `MESSAGED`
- Transactions: `from_account` -> `to_account`, relationship `TRANSFERRED_TO`
- Events: person to location, vehicle, or organization using `LOCATED_AT`, `USED`, or `WORKS_FOR`
- Ownership and case links are derived by the graph builder as `OWNS` and `INVOLVED_IN`

External aliases such as `PERSON_ID`, `PersonID`, and `personIdentifier` belong in a future provider-specific normalization adapter. The current normalization layer handles the known canonical package and deterministic whitespace cleanup only.