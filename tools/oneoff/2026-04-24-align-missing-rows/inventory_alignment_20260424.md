# wifi_llapi inventory alignment report

- generated_at: `2026-04-25T07:03:00.215497+00:00`
- mode: `apply`
- actions: `17`

## Renames (8)

| row | from | to | fields_changed |
| --- | --- | --- | --- |
| 66 | `D068_discoverymethodenabled_accesspoint_fils.yaml` | `D066_discoverymethodenabled_accesspoint_fils.yaml` | `id`: 'wifi-llapi-D068-discoverymethodenabled-accesspoint-fils' → 'wifi-llapi-D066-discoverymethodenabled-accesspoint-fils'<br>`source.row`: 68 → 66 |
| 67 | `D068_discoverymethodenabled_accesspoint_upr.yaml` | `D067_discoverymethodenabled_accesspoint_upr.yaml` | `id`: 'wifi-llapi-D068-discoverymethodenabled-accesspoint-upr' → 'wifi-llapi-D067-discoverymethodenabled-accesspoint-upr'<br>`source.row`: 68 → 67 |
| 109 | `D115_getstationstats_accesspoint.yaml` | `D109_getstationstats.yaml` | `id`: 'wifi-llapi-D115-getstationstats-accesspoint' → 'wifi-llapi-D109-getstationstats'<br>`source.row`: 115 → 109 |
| 110 | `D115_getstationstats_active.yaml` | `D110_getstationstats_active.yaml` | `id`: 'wifi-llapi-D115-getstationstats-active' → 'wifi-llapi-D110-getstationstats-active'<br>`source.row`: 115 → 110 |
| 111 | `D115_getstationstats_associationtime.yaml` | `D111_getstationstats_associationtime.yaml` | `id`: 'wifi-llapi-D115-getstationstats-associationtime' → 'wifi-llapi-D111-getstationstats-associationtime'<br>`source.row`: 115 → 111 |
| 112 | `D115_getstationstats_authenticationstate.yaml` | `D112_getstationstats_authenticationstate.yaml` | `id`: 'wifi-llapi-D115-getstationstats-authenticationstate' → 'wifi-llapi-D112-getstationstats-authenticationstate'<br>`source.row`: 115 → 112 |
| 113 | `D115_getstationstats_avgsignalstrength.yaml` | `D113_getstationstats_avgsignalstrength.yaml` | `id`: 'wifi-llapi-D115-getstationstats-avgsignalstrength' → 'wifi-llapi-D113-getstationstats-avgsignalstrength'<br>`source.row`: 115 → 113 |
| 114 | `D115_getstationstats_avgsignalstrengthbychain.yaml` | `D114_getstationstats_avgsignalstrengthbychain.yaml` | `id`: 'wifi-llapi-D115-getstationstats-avgsignalstrengthbychain' → 'wifi-llapi-D114-getstationstats-avgsignalstrengthbychain'<br>`source.row`: 115 → 114 |

## Move + Metadata Fix (2)

| row | from | to | fields_changed |
| --- | --- | --- | --- |
| 407 | `D495_retrycount_ssid_stats_basic.yaml` | `D407_retrycount_ssid_stats.yaml` | `id`: 'wifi-llapi-d495-retrycount-basic' → 'wifi-llapi-D407-retrycount'<br>`source.row`: 495 → 407 |
| 495 | `D495_retrycount_ssid_stats_verified.yaml` | `D495_retrycount_ssid_stats_verified.yaml` | `source.row`: 362 → 495 |

## Deletes (6)

| row | from | to | fields_changed |
| --- | --- | --- | --- |
| — | `D096_uapsdenable.yaml` | `—` | — |
| — | `D097_vendorie.yaml` | `—` | — |
| — | `D100_wmmenable.yaml` | `—` | — |
| — | `D102_configmethodssupported.yaml` | `—` | — |
| — | `D106_relaycredentialsenable.yaml` | `—` | — |
| — | `D474_channel_radio_37.yaml` | `—` | — |

## New from _template.yaml (1)

| row | from | to | fields_changed |
| --- | --- | --- | --- |
| 428 | `_template.yaml` | `D428_channel_neighbour.yaml` | `id`: None → 'wifi-llapi-D428-channel-neighbour'<br>`source.row`: None → 428<br>`source.object`: None → 'WiFi.AccessPoint.{i}.Neighbour.{i}.'<br>`source.api`: None → 'Channel' |

## Post state

```json
{
  "canonical_coverage": 294,
  "incl_template": 416,
  "liberal_missing": 0,
  "liberal_missing_rows": [],
  "support_rows": 415,
  "total_cases": 415
}
```
