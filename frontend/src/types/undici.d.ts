declare module 'undici' {
  export const setGlobalDispatcher: (dispatcher: unknown) => void;
  export interface AgentOptions {
    headersTimeout?: number;
    bodyTimeout?: number;
    connections?: number;
    pipelining?: number;
  }
  export class Agent {
    constructor(options?: AgentOptions);
  }
}
