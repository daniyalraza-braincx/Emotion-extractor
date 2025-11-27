# n8n Webhook Integration for Analyzed Call Results

This document explains how to set up the webhook integration to send analyzed call results to n8n (and then to Airtable).

## Overview

When a call analysis completes, the system can automatically send the analyzed results to a configured n8n webhook URL. This allows you to:
1. Receive analyzed call data in n8n
2. Transform/format the data as needed
3. Send it to Airtable (or any other destination)

## Setup Steps

### 1. Run Database Migration

First, add the `webhook_url` column to the organizations table:

```bash
cd api
python migrate_add_webhook_url.py
```

This will add the `webhook_url` column to the `organizations` table.

### 2. Create n8n Workflow

In n8n, create a new workflow with:

1. **Webhook Trigger Node**
   - Method: POST
   - Path: `/analyzed-call-results` (or any path you prefer)
   - Copy the webhook URL (e.g., `https://your-n8n-instance.com/webhook/analyzed-call-results`)

2. **Transform/Format Node** (optional)
   - Use this to reshape the data for Airtable
   - The webhook payload structure is documented below

3. **Airtable Node**
   - Configure your Airtable base and table
   - Map the fields from the webhook payload

### 3. Configure Webhook URL in Your App

1. Go to **Organization Settings** in the web app
2. Click **Configure** on the organization you want to set up
3. In the **n8n Webhook URL** section, click **Set Webhook** (or **Edit** if one exists)
4. Paste your n8n webhook URL
5. Click **Save**

The webhook URL is now configured for that organization.

## Webhook Payload Structure

When analysis completes, your n8n webhook will receive a POST request with the following JSON structure:

```json
{
  "event": "call_analysis_completed",
  "call_id": "call_abc123...",
  "organization_id": 1,
  "analysis_status": "completed",
  "call_metadata": {
    "call_id": "call_abc123...",
    "agent_id": "agent_xyz789...",
    "agent_name": "Customer Support Agent",
    "start_timestamp": "2024-01-15T10:30:00Z",
    "end_timestamp": "2024-01-15T10:35:00Z",
    "duration_ms": 300000,
    "user_phone_number": "+1234567890",
    "call_title": "Customer Support Call",
    "call_summary": "Customer called about product issue...",
    "call_purpose": "Support Request",
    "overall_emotion": {
      "label": "neutral",
      "score": 0.65
    },
    "overall_emotion_label": "neutral",
    "recording_url": "https://..."
  },
  "analysis_results": {
    "filename": "call_abc123_combined",
    "prosody": [
      {
        "time_start": 0.0,
        "time_end": 5.0,
        "primary_category": "positive",
        "source": "prosody",
        "speaker": "agent",
        "text": "Hello, how can I help you?",
        "top_emotions": [
          {
            "name": "happiness",
            "score": 0.85,
            "percentage": 85.0,
            "category": "positive"
          }
        ]
      }
    ],
    "burst": [
      {
        "time_start": 0.0,
        "time_end": 2.5,
        "primary_category": "neutral",
        "source": "burst",
        "speaker": "agent"
      }
    ],
    "metadata": {
      "retell_call_id": "call_abc123...",
      "recording_multi_channel_url": "https://...",
      "start_timestamp": "2024-01-15T10:30:00Z",
      "end_timestamp": "2024-01-15T10:35:00Z",
      "duration_ms": 300000,
      "agent": {
        "id": "agent_xyz789...",
        "name": "Customer Support Agent"
      },
      "retell_transcript_available": true,
      "retell_transcript_segments": [...],
      "category_counts": {
        "positive": 10,
        "neutral": 15,
        "negative": 5
      },
      "overall_call_emotion": {
        "label": "neutral",
        "score": 0.65
      }
    },
    "summary": "The call was about a product issue..."
  }
}
```

## Key Fields for Airtable

Common fields you might want to map to Airtable:

- `call_metadata.call_id` - Unique call identifier
- `call_metadata.agent_id` - Agent who handled the call
- `call_metadata.agent_name` - Agent name
- `call_metadata.start_timestamp` - Call start time
- `call_metadata.duration_ms` - Call duration in milliseconds
- `call_metadata.call_title` - Generated call title
- `call_metadata.call_summary` - Call summary
- `call_metadata.call_purpose` - Call purpose
- `call_metadata.overall_emotion_label` - Overall emotion (positive/neutral/negative)
- `analysis_results.metadata.category_counts` - Emotion category counts
- `analysis_results.summary` - Analysis summary

## Error Handling

- If the webhook URL is not configured, no webhook is sent (no error)
- If the webhook request fails (network error, timeout, etc.), it's logged but doesn't affect the analysis
- The analysis will still complete successfully even if the webhook fails

## Testing

To test the webhook:

1. Configure the webhook URL in Organization Settings
2. Analyze a call (either manually or wait for automatic analysis)
3. Check your n8n workflow execution history to see if the webhook was received
4. Verify the data format matches your expectations

## Troubleshooting

- **Webhook not received**: Check that the webhook URL is correctly configured and accessible
- **Timeout errors**: The webhook has a 10-second timeout. If your n8n instance is slow, consider using a queue system
- **Data format issues**: Check the payload structure above and adjust your n8n transform node accordingly

## API Endpoint

You can also update the webhook URL via the API:

```bash
PUT /organizations/{org_id}
Content-Type: application/json
Authorization: Bearer <token>

{
  "webhook_url": "https://your-n8n-instance.com/webhook/analyzed-call-results"
}
```

To clear the webhook URL, send an empty string or null:

```json
{
  "webhook_url": ""
}
```

