// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { AggregateResponse } from '@/api/generated/model'
import { WorkbenchContextProvider } from '@/components/workbench/workbench-context'
import { AiReviewWorkspace } from './ai-review-workspace'

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

vi.mock('@/api/generated/ai-proposals/ai-proposals', () => ({
  useListAgents: () => ({
    data: [{
      id: '00000000-0000-0000-0000-000000000001',
      name: 'Clinical agent',
      description: null,
      capabilities: ['clinical_proposal_v1'],
      provider: 'aws_bedrock',
      model_id: 'anthropic.claude-sonnet',
      revision: 1,
    }],
  }),
}))

vi.mock('@/api/generated/sdtm/sdtm', () => ({
  createProposal: vi.fn(),
  getListProposalsQueryKey: (sdtmId: string) => [
    `/api/v1/sdtm-workbenches/${sdtmId}/proposals`,
  ],
  postAcceptProposal: vi.fn(),
  postRejectProposal: vi.fn(),
  postRequestProposalRevision: vi.fn(),
  useListProposals: () => ({
    data: { items: [] },
    isLoading: false,
  }),
}))

describe('AiReviewWorkspace', () => {
  it('separates the human review workspace from the SDTM agent rail', () => {
    const aggregate = {
      id: 'sdtm-1',
      study_id: 'study-1',
      code: 'SDTM1',
      name: 'SDTM workbench',
      status: 'draft',
      revision: 3,
    } as AggregateResponse
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })

    const { container } = render(
      <QueryClientProvider client={queryClient}>
        <WorkbenchContextProvider
          value={{
            aggregate,
            revision: aggregate.revision,
            studyId: aggregate.study_id,
            ifMatch: () => ({ headers: { 'If-Match': '"revision-3"' } }),
          }}
        >
          <AiReviewWorkspace
            sdtmId="sdtm-1"
            proposalType="sdtm_domain_mapping"
            title="Domain Mapping proposal"
            description="Review the proposed domain mapping."
            needsDomain
          />
        </WorkbenchContextProvider>
      </QueryClientProvider>,
    )

    expect(container.querySelector('main')).not.toBeNull()
    expect(container.querySelector('aside')).not.toBeNull()
    expect(screen.getByText('Human review')).toBeTruthy()
    expect(screen.getByText('SDTM Agent')).toBeTruthy()
    expect(screen.getByLabelText('Guidance for the agent')).toBeTruthy()
    expect(screen.getByLabelText('Platform agent')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Generate proposal' })).toBeTruthy()
    expect(screen.getByText('No proposal is ready for review')).toBeTruthy()
  })
})
