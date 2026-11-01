import { MessageSquare } from 'lucide-react';
import { PlaceholderPage } from './PlaceholderPage';

export function AssistantPage() {
  return (
    <PlaceholderPage
      Icon={MessageSquare}
      title="Aviation Assistant"
      description="A RAG-powered aviation intelligence assistant. Ask natural-language questions about flights, delays, routes, airlines and historical performance. Powered by vector search over BTS documentation."
      status="RAG System Planned"
      features={[
        'Natural-language query interface',
        'RAG pipeline over BTS data and aviation docs',
        'Structured data query generation',
        'Context-aware follow-up questions',
        'Source citation and confidence display',
        'Aviation terminology understanding',
      ]}
    />
  );
}

