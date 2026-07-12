export interface Trader {
  id: string;
  name: string;
  email: string;
  totalPnl: number;
  winRate: number;
  sharpeRatio: number;
  totalTrades: number;
  aum: number;
  status: "active" | "inactive" | "suspended";
  joinedDate: string;
  recentPerformance: number[];
}

export const mockTraders: Trader[] = [
  {
    id: "trader-1",
    name: "John Carter",
    email: "john@example.com",
    totalPnl: 284750,
    winRate: 68.5,
    sharpeRatio: 1.84,
    totalTrades: 847,
    aum: 2500000,
    status: "active",
    joinedDate: "2024-03-15",
    recentPerformance: [2.1, -0.5, 1.8, 3.2, -1.1, 2.4, 0.9, 1.5, -0.3, 2.8],
  },
  {
    id: "trader-2",
    name: "Sarah Chen",
    email: "sarah@example.com",
    totalPnl: 421300,
    winRate: 72.1,
    sharpeRatio: 2.12,
    totalTrades: 1240,
    aum: 5200000,
    status: "active",
    joinedDate: "2024-01-08",
    recentPerformance: [3.1, 1.2, -0.8, 2.5, 1.9, -0.2, 2.7, 3.5, 1.1, 2.0],
  },
  {
    id: "trader-3",
    name: "Mike Torres",
    email: "mike@example.com",
    totalPnl: 156200,
    winRate: 61.3,
    sharpeRatio: 1.45,
    totalTrades: 523,
    aum: 1800000,
    status: "active",
    joinedDate: "2024-06-01",
    recentPerformance: [1.5, 0.8, -1.2, 2.0, 0.5, 1.7, -0.6, 1.2, 0.3, 1.9],
  },
  {
    id: "trader-4",
    name: "Emma Wilson",
    email: "emma@example.com",
    totalPnl: 312800,
    winRate: 65.9,
    sharpeRatio: 1.72,
    totalTrades: 956,
    aum: 3700000,
    status: "active",
    joinedDate: "2024-04-20",
    recentPerformance: [2.5, -1.0, 1.5, 2.8, 0.7, 1.3, -0.4, 2.1, 1.6, 2.3],
  },
  {
    id: "trader-5",
    name: "Alex Patel",
    email: "alex@example.com",
    totalPnl: 189400,
    winRate: 59.8,
    sharpeRatio: 1.31,
    totalTrades: 678,
    aum: 2100000,
    status: "inactive",
    joinedDate: "2024-07-10",
    recentPerformance: [0.8, -1.5, 1.0, 1.2, -0.9, 0.5, 1.8, -0.2, 0.7, 1.1],
  },
  {
    id: "trader-6",
    name: "Lisa Kim",
    email: "lisa@example.com",
    totalPnl: 534600,
    winRate: 75.4,
    sharpeRatio: 2.41,
    totalTrades: 1580,
    aum: 6800000,
    status: "active",
    joinedDate: "2023-11-05",
    recentPerformance: [3.8, 2.1, 0.5, 1.9, 2.5, -0.1, 3.2, 1.8, 2.6, 1.4],
  },
  {
    id: "trader-7",
    name: "David Park",
    email: "david@example.com",
    totalPnl: 98700,
    winRate: 55.2,
    sharpeRatio: 1.08,
    totalTrades: 345,
    aum: 950000,
    status: "active",
    joinedDate: "2024-09-01",
    recentPerformance: [0.5, -0.8, 1.1, -0.3, 0.9, -0.5, 0.7, 0.2, -0.1, 0.6],
  },
  {
    id: "trader-8",
    name: "Rachel Green",
    email: "rachel@example.com",
    totalPnl: 245600,
    winRate: 63.7,
    sharpeRatio: 1.58,
    totalTrades: 789,
    aum: 2900000,
    status: "suspended",
    joinedDate: "2024-05-12",
    recentPerformance: [1.8, -0.2, 2.3, -1.5, 1.6, 2.0, -1.8, 0.4, 1.2, -0.6],
  },
];