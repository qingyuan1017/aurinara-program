import { type FormEvent, useCallback, useEffect, useRef, useState } from 'react'
import { Archive, Bot, Check, Plus, Send, Square, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Textarea } from '@/components/ui/textarea'
import {
  playgroundApi,
  type PlaygroundAgent,
  type PlaygroundConversation,
  type PlaygroundEvent,
} from '@/lib/playground-client'

type Message = { id: string; role: 'user' | 'assistant'; text: string }
type Approval = Extract<PlaygroundEvent, { type: 'approval_required' }>

export function Playground() {
  const [agents, setAgents] = useState<PlaygroundAgent[]>([])
  const [agentId, setAgentId] = useState('')
  const [conversations, setConversations] = useState<PlaygroundConversation[]>([])
  const [conversation, setConversation] = useState<PlaygroundConversation | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [prompt, setPrompt] = useState('')
  const [busy, setBusy] = useState(false)
  const [approval, setApproval] = useState<Approval | null>(null)
  const [toolStatus, setToolStatus] = useState('')
  const [error, setError] = useState('')
  const controller = useRef<AbortController | null>(null)
  const historyRequest = useRef(0)

  const openConversation = useCallback(async (item: PlaygroundConversation) => {
    const requestId = ++historyRequest.current
    setConversation(item); setMessages([]); setToolStatus('')
    setApproval(item.pending_interrupt_id ? { type: 'approval_required', interrupt_id: item.pending_interrupt_id, tool_name: item.pending_tool_name ?? 'tool', summary: 'This saved run is waiting for your approval.' } : null)
    const history = await playgroundApi.messages(item.id)
    if (requestId === historyRequest.current) setMessages(history.filter((message) => message.role === 'user' || message.role === 'assistant').map((message) => ({ id: message.id, role: message.role as 'user' | 'assistant', text: message.content })))
  }, [])

  const loadConversations = useCallback(async (selectedAgentId: string, preferredId?: string, loadHistory = true) => {
    const items = await playgroundApi.conversations(selectedAgentId)
    setConversations(items)
    const selected = items.find((item) => item.id === preferredId) ?? items[0] ?? null
    if (selected && loadHistory) await openConversation(selected)
    else setConversation(selected)
  }, [openConversation])

  useEffect(() => {
    void playgroundApi.agents().then(async (items) => { const firstId = items[0]?.id ?? ''; setAgents(items); setAgentId(firstId); if (firstId) await loadConversations(firstId) })
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : 'Unable to load agents'))
    return () => controller.current?.abort()
  }, [loadConversations])

  const startNew = () => { historyRequest.current += 1; controller.current?.abort(); setConversation(null); setMessages([]); setApproval(null); setToolStatus(''); setError(''); setBusy(false) }
  const archiveCurrent = async () => { if (!conversation) return; await playgroundApi.updateConversation(conversation.id, { state: 'archived' }); startNew(); await loadConversations(agentId) }

  const applyEvent = (assistantId: string, event: PlaygroundEvent) => {
    if (event.type === 'text_delta') setMessages((items) => items.map((item) => item.id === assistantId ? { ...item, text: item.text + event.text } : item))
    if (event.type === 'tool_status') setToolStatus(`${event.tool_name} · ${event.status}`)
    if (event.type === 'approval_required') { setApproval(event); setToolStatus(`${event.tool_name} · awaiting approval`) }
    if (event.type === 'error') setError(event.message)
  }

  const run = async (kind: 'message' | 'approval', value: string, pending?: Approval, decision?: 'approve' | 'deny') => {
    if (!agentId) return
    setBusy(true); setError('')
    try {
      const current = conversation ?? await playgroundApi.createConversation(agentId)
      if (!conversation) setConversation(current)
      const assistantId = crypto.randomUUID()
      setMessages((items) => [...items, { id: assistantId, role: 'assistant', text: '' }])
      controller.current = new AbortController()
      if (kind === 'message') await playgroundApi.message(current.id, value, controller.current.signal, (event) => applyEvent(assistantId, event))
      else if (pending && decision) await playgroundApi.approval(current.id, pending.interrupt_id, decision, controller.current.signal, (event) => applyEvent(assistantId, event))
      await loadConversations(agentId, current.id, false)
    } catch (reason) {
      if (!(reason instanceof DOMException && reason.name === 'AbortError')) setError(reason instanceof Error ? reason.message : 'Agent request failed')
    } finally { setBusy(false); controller.current = null }
  }

  const submit = (event: FormEvent) => { event.preventDefault(); const value = prompt.trim(); if (!value || busy || approval) return; setPrompt(''); setMessages((items) => [...items, { id: crypto.randomUUID(), role: 'user', text: value }]); void run('message', value) }
  const decide = (decision: 'approve' | 'deny') => { if (!approval) return; const pending = approval; setApproval(null); void run('approval', '', pending, decision) }

  return (
    <div className="grid min-h-[calc(100vh-8rem)] gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
      <Card className="min-h-0">
        <CardHeader><CardTitle>Conversations</CardTitle><CardDescription>Saved in AgentCore Memory</CardDescription></CardHeader>
        <CardContent className="flex max-h-[calc(100vh-15rem)] flex-col gap-3 overflow-auto">
          <select className="border-input bg-background h-9 rounded-md border px-3 text-sm" value={agentId} disabled={busy} onChange={(event) => { const nextId = event.target.value; startNew(); setConversations([]); setAgentId(nextId); void loadConversations(nextId).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : 'Unable to load conversations')) }}>{agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}</select>
          <Button onClick={startNew}><Plus />New conversation</Button>
          <div className="grid gap-2">{conversations.map((item) => <button key={item.id} type="button" onClick={() => void openConversation(item).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : 'Unable to load AgentCore history'))} className={`rounded-md border p-3 text-left ${conversation?.id === item.id ? 'border-primary bg-accent' : 'hover:bg-accent'}`}><span className="block truncate text-sm font-medium">{item.title ?? 'New conversation'}</span><span className="text-muted-foreground block text-xs">{new Date(item.updated_at).toLocaleString()}</span></button>)}</div>
        </CardContent>
      </Card>
      <div className="grid min-h-0 grid-rows-[auto_1fr_auto] gap-4">
        <div className="flex items-center justify-between"><div><h2 className="font-semibold">{conversation?.title ?? 'New conversation'}</h2><p className="text-muted-foreground text-sm">History and recall stay with this AgentCore session.</p></div>{conversation && <Button variant="outline" onClick={() => void archiveCurrent()}><Archive />Archive</Button>}</div>
        <Card className="min-h-80 overflow-auto" aria-live="polite"><CardContent className="flex flex-col gap-4 pt-6">
          {messages.length === 0 && <div className="text-muted-foreground grid place-items-center gap-2 py-20 text-center"><Bot className="size-10" /><strong className="text-foreground">Start a conversation</strong><span>{agents.find((agent) => agent.id === agentId)?.description ?? 'Choose an agent and ask a question.'}</span></div>}
          {messages.map((message) => <div key={message.id} className={message.role === 'user' ? 'ml-auto max-w-[80%] rounded-xl bg-primary px-4 py-3 text-primary-foreground' : 'max-w-[80%] rounded-xl bg-muted px-4 py-3'}><div className="mb-1 text-xs font-semibold opacity-70">{message.role === 'user' ? 'You' : 'Agent'}</div><div className="whitespace-pre-wrap">{message.text || (busy ? 'Thinking…' : '')}</div></div>)}
          {toolStatus && <div className="text-muted-foreground text-sm">{toolStatus}</div>}
          {approval && <Card className="border-amber-500/50 bg-amber-500/5"><CardHeader><CardTitle className="text-base">Approve this write?</CardTitle><CardDescription>{approval.summary ?? `${approval.tool_name} wants to change data.`}</CardDescription></CardHeader><CardContent className="space-y-3">{approval.arguments !== undefined && <details className="text-sm"><summary>Review details</summary><pre className="mt-2 overflow-auto rounded bg-muted p-3">{JSON.stringify(approval.arguments, null, 2)}</pre></details>}<div className="flex gap-2"><Button onClick={() => decide('approve')}><Check />Approve once</Button><Button variant="outline" onClick={() => decide('deny')}><X />Deny</Button></div></CardContent></Card>}
          {error && <div className="text-destructive text-sm">{error}</div>}
        </CardContent></Card>
        <form className="flex items-end gap-2" onSubmit={submit}><Textarea aria-label="Message" rows={3} value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="Ask the selected agent…" disabled={!agentId || busy || Boolean(approval)} />{busy ? <Button type="button" variant="outline" onClick={() => controller.current?.abort()}><Square />Stop</Button> : <Button disabled={!agentId || !prompt.trim() || Boolean(approval)}><Send />Send</Button>}</form>
      </div>
    </div>
  )
}
