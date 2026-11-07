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
  insights: Insights;
}

export interface TopicForecast {
  tag: string;
  problems: number;
  recall_now: number;
  recall_later: number;
}

export interface MistakeRecovery {
  kind: string;
  times: number;
  last_seen: string;
  clean_reviews_since: number;
}

export interface OverconfidentReview {
  platform: string;
  problem_id: string;
  title: string;
  url: string;
  rated_easy_at: string;
  forgot_at: string;
}

export interface CalibrationBin {
  low: number;
  high: number;
  reviews: number;
  predicted: number;
  recalled: number;
}

export interface Insights {
  horizon_days: number;
  forecast: TopicForecast[];
  recovery: MistakeRecovery[];
  overconfidence: OverconfidentReview[];
  calibration: CalibrationBin[];
}
