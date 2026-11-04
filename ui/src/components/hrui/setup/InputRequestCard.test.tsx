import { fireEvent, render, screen } from '@testing-library/react';
import { inputRequestOf, type InputRequest } from '@/lib/conversation';
import { incompleteWhy } from './AgentTurns';
import { InputRequestCard, requestExpired } from './InputRequestCard';

const ask = (over: Partial<InputRequest>): InputRequest => ({ id: 'inreq_1', kind: 'free_text', prompt: 'Which one?', ...over });

describe('the question a task ended on', () => {
  it('takes one option id for a choice, and shows its label as the message', () => {
    const on = jest.fn();
    render(<InputRequestCard request={ask({ kind: 'choice', options: [{ id: 'l', label: 'Left' }, { id: 'r', label: 'Right' }] })} onAnswer={on} />);
    fireEvent.click(screen.getByRole('button', { name: 'Right' }));
    expect(on).toHaveBeenCalledWith('r', 'Right');
  });

  it('answers a confirm with no options yes or no', () => {
    const on = jest.fn();
    render(<InputRequestCard request={ask({ kind: 'confirm' })} onAnswer={on} />);
    fireEvent.click(screen.getByRole('button', { name: 'No' }));
    expect(on).toHaveBeenCalledWith('no', 'No');
  });

  it('never shows a secret: a password field, and a thread message that does not hold it', () => {
    const on = jest.fn();
    render(<InputRequestCard request={ask({ kind: 'secret', prompt: 'The token?' })} onAnswer={on} />);
    const box = screen.getByLabelText('The token?') as HTMLInputElement;
    expect(box.type).toBe('password');
    expect(box.autocomplete).toBe('off');
    fireEvent.change(box, { target: { value: 's3cret-value' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send answer' }));
    expect(on).toHaveBeenCalledWith('s3cret-value', 'Answer sent privately');
    expect(box.value).toBe('');
  });

  it('sends nothing empty, and shows free text as written', () => {
    const on = jest.fn();
    render(<InputRequestCard request={ask({})} onAnswer={on} />);
    expect((screen.getByRole('button', { name: 'Send answer' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('Which one?'), { target: { value: ' blue ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send answer' }));
    expect(on).toHaveBeenCalledWith('blue', 'blue');
  });

  it('says so when it has expired, and offers nothing to send', () => {
    expect(requestExpired(ask({ expires_at: 100 }), 100)).toBe(true);
    expect(requestExpired(ask({ expires_at: 101 }), 100)).toBe(false);
    expect(requestExpired(ask({}), 100)).toBe(false);
    render(<InputRequestCard request={ask({ expires_at: 1 })} onAnswer={jest.fn()} />);
    expect(screen.getByRole('status').textContent).toContain('expired');
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('reads the question from the end of a response, and an incomplete turn says why', () => {
    expect(inputRequestOf({ output: [{ type: 'message' }, { type: 'input_request', id: 'inreq_9', kind: 'confirm', prompt: 'p' }] })?.id).toBe('inreq_9');
    expect(inputRequestOf({ output: [{ type: 'message' }] })).toBeUndefined();
    expect(inputRequestOf(undefined)).toBeUndefined();
    expect(incompleteWhy('input_required')).toBe('Waiting for your answer.');
  });
});
