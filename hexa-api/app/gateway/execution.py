from __future__ import annotations


class PublicExecution:
    def __init__(self):
        self.reasoning = ''
        self.steps = {}

    def consume(self, event):
        event_type = event.get('type', '')
        if event_type == 'response.reasoning_summary_text.delta' and isinstance(event.get('delta'), str):
            self.reasoning = (self.reasoning + event['delta'])[:32000]
        item = event.get('item')
        if isinstance(item, dict):
            self.consume_item(item)
        response = event.get('response')
        if isinstance(response, dict):
            for output in response.get('output', []):
                if isinstance(output, dict):
                    self.consume_item(output)

    def consume_item(self, item):
        kind = item.get('type', '')
        if kind == 'reasoning' and not self.reasoning:
            self.reasoning = ''.join(part.get('text', '') for part in item.get('summary', []) if isinstance(part, dict) and isinstance(part.get('text'), str))[:32000]
        if isinstance(kind, str) and (kind == 'function_call' or kind.endswith('_call')):
            identity = item.get('id') or item.get('call_id')
            if isinstance(identity, str) and (identity in self.steps or len(self.steps) < 100):
                self.steps[identity] = {
                    'id': identity[:255],
                    'name': str(item.get('name') or kind)[:255],
                    'status': str(item.get('status') or 'in_progress')[:64],
                }

    def snapshot(self):
        return {'reasoning': self.reasoning, 'steps': list(self.steps.values())}
