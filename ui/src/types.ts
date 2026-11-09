// Mirrors the Dashboard model in src/dsa_coach_mcp/models.py.

export interface PlatformProgress {
  platform: string;
  source: "platform" | "reported";
  problems: number;
  reviews: number;
  due_now: number;
}

export interface ReviewCard {
  platform: string;
  problem_id: string;
  title: string;
  url: string;
  due: string;
  stability: number | null;
  difficulty: number | null;
  retrievability: number | null;
  reviews: number;
}

export interface MistakeKind {
  kind: string;
  count: number;
  last_seen: string;
}

export interface MistakeCount {
  kind: string;
  key: string;
  count: number;
}

export interface MistakePatterns {
  kinds: MistakeKind[];
  by_tag: MistakeCount[];
  by_platform: MistakeCount[];
  by_month: MistakeCount[];
}

export interface Dashboard {
  progress: PlatformProgress[];
  due: ReviewCard[];
  patterns: MistakePatterns;
}
