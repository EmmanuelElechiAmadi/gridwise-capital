//+------------------------------------------------------------------+
//|                                              mt5_bridge_ea.mq5   |
//|  Bridge between MT5 and Python via JSON files (Mac-compatible)   |
//+------------------------------------------------------------------+
#property strict
#property version   "1.11"

// ── File names (written to MT5 Files folder) ──
#define FILE_ACCOUNT   "mt5_account.json"
#define FILE_TICK      "mt5_tick.json"
#define FILE_POSITIONS "mt5_positions.json"
#define FILE_ORDERS    "mt5_orders.json"
#define FILE_CMD       "mt5_cmd.json"
#define FILE_CMD_RESULT "mt5_cmd_result.json"

// NOTE: Symbols must match EXACTLY what the broker provides.
// The EA auto-detects gold symbols present in the terminal at startup and
// merges them with this fallback list, so ticks are written even when the
// broker uses a different suffix (XAUUSD, XAUUSDm, GOLD, ...).
string g_symbols[] = {"XAUUSD.r", "XAUUSD", "XAUUSDm", "GOLD", "XAU", "EURUSD.r", "EURUSD", "GBPUSD.r", "GBPUSD", "USDJPY.r", "USDJPY"};
int g_timer_sec = 2;   // increased from 1 — Wine filesystem needs more time

//+------------------------------------------------------------------+
int OnInit() {
   EventSetTimer(g_timer_sec);
   DetectSymbols();
   Print("✅ mt5_bridge_ea started, timer interval ", g_timer_sec, " sec, symbols: ", ArraySize(g_symbols));
   return(INIT_SUCCEEDED);
}

// ── Auto-detect the broker's gold symbols from Market Watch ────────
void DetectSymbols() {
   int total = SymbolsTotal(true);            // only Market Watch symbols
   for (int i = 0; i < total; i++) {
      string name = SymbolName(i, true);
      // Focus on gold + the symbols we may trade
      bool wanted = (StringFind(name, "XAU") >= 0) || (StringFind(name, "GOLD") >= 0)
                    || (StringFind(name, "EURUSD") >= 0) || (StringFind(name, "GBPUSD") >= 0)
                    || (StringFind(name, "USDJPY") >= 0);
      if (!wanted) continue;
      if (ArraySearch(g_symbols, name) < 0) {
         int sz = ArraySize(g_symbols);
         ArrayResize(g_symbols, sz + 1);
         g_symbols[sz] = name;
         Print("➕ Auto-detected symbol: ", name);
      }
   }
}

// ── Case-insensitive array search ─────────────────────────────────
int ArraySearch(string &arr[], string value) {
   int n = ArraySize(arr);
   for (int i = 0; i < n; i++)
      if (StringCompare(arr[i], value, false) == 0) return i;
   return -1;
}

// ── Register a symbol so ticks are written for it ─────────────────
void EnsureSymbol(string name) {
   if (ArraySearch(g_symbols, name) < 0) {
      int sz = ArraySize(g_symbols);
      ArrayResize(g_symbols, sz + 1);
      g_symbols[sz] = name;
   }
}

// ── Find an available symbol matching the requested one ─────────────
// Handles broker suffix differences: "XAUUSD.r" <-> "XAUUSD" <-> "XAUUSDm".
string FindUsableSymbol(string requested) {
   string base = requested;
   if (StringLen(base) > 2 && (StringSubstr(base, StringLen(base)-2) == ".r"
                            || StringSubstr(base, StringLen(base)-2) == ".m"))
      base = StringSubstr(base, 0, StringLen(base)-2);
   // 1) stripped base (e.g. XAUUSD)
   if (base != requested && SymbolSelect(base, true)) return base;
   // 2) exact requested (e.g. XAUUSD.r if it really exists)
   if (SymbolSelect(requested, true)) return requested;
   // 3) any detected symbol containing the base (case-insensitive)
   for (int i = 0; i < ArraySize(g_symbols); i++) {
      if (StringFind(g_symbols[i], base, 0) >= 0) {
         if (SymbolSelect(g_symbols[i], true)) return g_symbols[i];
      }
   }
   // 4) any detected gold symbol
   for (int i = 0; i < ArraySize(g_symbols); i++) {
      string nm = g_symbols[i];
      if (StringFind(nm, "XAU") >= 0 || StringFind(nm, "GOLD") >= 0) {
         if (SymbolSelect(nm, true)) return nm;
      }
   }
   return "";
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason) {
   EventKillTimer();
   // Write empty state on shutdown
   WriteAccount();
   WriteTick(g_symbols);
   WritePositions();
   WriteOrders();
   Print("🛑 mt5_bridge_ea stopped");
}

//+------------------------------------------------------------------+
void OnTimer() {
   // ⚡ CRITICAL: Process command BEFORE writing data files.
   //    Under Wine, writing 4 files can take 1-2 seconds. If we wait
   //    until after the writes, the Python server times out (504).
   ProcessCommand();

   // Then update the data files for the Python server.
   WriteAccount();
   WriteTick(g_symbols);
   WritePositions();
   WriteOrders();
}
//+------------------------------------------------------------------+

// ── Helper: write a string to a file ──
void WriteFile(string filename, string content) {
   int h = FileOpen(filename, FILE_TXT|FILE_WRITE, 0, CP_UTF8);
   if (h != INVALID_HANDLE) {
      FileWrite(h, content);
      FileClose(h);
   }
}

// ── Ensure volume is valid for a symbol (min / step / max) ──────────
double NormalizeVolume(string symbol, double requested) {
   double vmin  = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
   double vstep = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
   double vmax  = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
   if (vstep <= 0) vstep = 0.01;
   if (vmin  <= 0) vmin  = 0.01;
   if (vmax  <= 0) vmax  = 100.0;
   // Round UP to the nearest valid step (never below min / above max).
   // The small epsilon prevents float error (0.01/0.01 -> 1.0000...2) from
   // rounding 0.01 up to 0.02.
   double vol = MathCeil(requested / vstep - 0.0001) * vstep;
   if (vol < vmin)  vol = vmin;
   if (vol > vmax)  vol = vmax;
   return NormalizeDouble(vol, 2);
}

// ── Write a command result. retcode -1 = "keep waiting" (Python skips). ──
void WriteCmdResult(int retcode, string comment, long ticket = 0, string symbol = "") {
   string json = "{";
   json += "\"retcode\":" + IntegerToString(retcode) + ",";
   json += "\"ticket\":" + IntegerToString((int)ticket) + ",";
   json += "\"symbol\":\"" + symbol + "\",";
   json += "\"comment\":\"" + comment + "\"";
   json += "}";
   WriteFile(FILE_CMD_RESULT, json);
}

// ── Write account info ──
void WriteAccount() {
   string json = "{";
   json += "\"login\":" + IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN)) + ",";
   json += "\"balance\":" + DoubleToString(AccountInfoDouble(ACCOUNT_BALANCE), 2) + ",";
   json += "\"equity\":" + DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY), 2) + ",";
   json += "\"profit\":" + DoubleToString(AccountInfoDouble(ACCOUNT_PROFIT), 2) + ",";
   json += "\"margin_free\":" + DoubleToString(AccountInfoDouble(ACCOUNT_MARGIN_FREE), 2) + ",";
   json += "\"leverage\":" + IntegerToString((int)AccountInfoInteger(ACCOUNT_LEVERAGE)) + ",";
   json += "\"server\":\"" + AccountInfoString(ACCOUNT_SERVER) + "\",";
   json += "\"name\":\"" + AccountInfoString(ACCOUNT_NAME) + "\",";
   json += "\"currency\":\"" + AccountInfoString(ACCOUNT_CURRENCY) + "\"";
   json += "}";
   WriteFile(FILE_ACCOUNT, json);
}

// ── Write latest tick for symbols ──
void WriteTick(string &syms[]) {
   string json = "[";
   int n = ArraySize(syms);
   for (int i = 0; i < n; i++) {
      MqlTick tick;
      if (SymbolInfoTick(syms[i], tick)) {
         if (i > 0) json += ",";
         double point = SymbolInfoDouble(syms[i], SYMBOL_POINT);
         int spread = (point > 0) ? (int)((tick.ask - tick.bid) / point) : 0;
         json += "{";
         json += "\"symbol\":\"" + syms[i] + "\",";
         json += "\"bid\":" + DoubleToString(tick.bid, (int)SymbolInfoInteger(syms[i], SYMBOL_DIGITS)) + ",";
         json += "\"ask\":" + DoubleToString(tick.ask, (int)SymbolInfoInteger(syms[i], SYMBOL_DIGITS)) + ",";
         json += "\"spread\":" + IntegerToString(spread) + ",";
         json += "\"time\":" + IntegerToString((int)tick.time);
         json += "}";
      }
   }
   json += "]";
   WriteFile(FILE_TICK, json);
}

// ── Write positions ──
void WritePositions() {
   string json = "[";
   int total = PositionsTotal();
   bool first = true;
   for (int i = 0; i < total; i++) {
      ulong ticket = PositionGetTicket(i);
      if (PositionSelectByTicket(ticket)) {
         if (!first) json += ",";
         first = false;
         json += "{";
         json += "\"ticket\":" + IntegerToString((int)ticket) + ",";
         json += "\"symbol\":\"" + PositionGetString(POSITION_SYMBOL) + "\",";
         json += "\"type\":\"" + (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY ? "buy" : "sell") + "\",";
         json += "\"volume\":" + DoubleToString(PositionGetDouble(POSITION_VOLUME), 2) + ",";
         json += "\"open_price\":" + DoubleToString(PositionGetDouble(POSITION_PRICE_OPEN), (int)SymbolInfoInteger(PositionGetString(POSITION_SYMBOL), SYMBOL_DIGITS)) + ",";
         json += "\"sl\":" + DoubleToString(PositionGetDouble(POSITION_SL), (int)SymbolInfoInteger(PositionGetString(POSITION_SYMBOL), SYMBOL_DIGITS)) + ",";
         json += "\"tp\":" + DoubleToString(PositionGetDouble(POSITION_TP), (int)SymbolInfoInteger(PositionGetString(POSITION_SYMBOL), SYMBOL_DIGITS)) + ",";
         json += "\"profit\":" + DoubleToString(PositionGetDouble(POSITION_PROFIT), 2) + ",";
         json += "\"magic\":" + IntegerToString((int)PositionGetInteger(POSITION_MAGIC));
         json += "}";
      }
   }
   json += "]";
   WriteFile(FILE_POSITIONS, json);
}

// ── Write pending orders ──
void WriteOrders() {
   string json = "[";
   int total = OrdersTotal();
   bool first = true;
   for (int i = 0; i < total; i++) {
      ulong ticket = OrderGetTicket(i);
      if (OrderSelect(ticket)) {
         if (!first) json += ",";
         first = false;
         string type_str = "unknown";
         ENUM_ORDER_TYPE ot = (ENUM_ORDER_TYPE)OrderGetInteger(ORDER_TYPE);
         if (ot == ORDER_TYPE_BUY_LIMIT) type_str = "buy_limit";
         else if (ot == ORDER_TYPE_SELL_LIMIT) type_str = "sell_limit";
         else if (ot == ORDER_TYPE_BUY_STOP) type_str = "buy_stop";
         else if (ot == ORDER_TYPE_SELL_STOP) type_str = "sell_stop";

         json += "{";
         json += "\"ticket\":" + IntegerToString((int)OrderGetInteger(ORDER_TICKET)) + ",";
         json += "\"symbol\":\"" + OrderGetString(ORDER_SYMBOL) + "\",";
         json += "\"type\":\"" + type_str + "\",";
         json += "\"volume\":" + DoubleToString(OrderGetDouble(ORDER_VOLUME_INITIAL), 2) + ",";
         json += "\"price\":" + DoubleToString(OrderGetDouble(ORDER_PRICE_OPEN), (int)SymbolInfoInteger(OrderGetString(ORDER_SYMBOL), SYMBOL_DIGITS)) + ",";
         json += "\"sl\":" + DoubleToString(OrderGetDouble(ORDER_SL), (int)SymbolInfoInteger(OrderGetString(ORDER_SYMBOL), SYMBOL_DIGITS)) + ",";
         json += "\"tp\":" + DoubleToString(OrderGetDouble(ORDER_TP), (int)SymbolInfoInteger(OrderGetString(ORDER_SYMBOL), SYMBOL_DIGITS)) + ",";
         json += "\"magic\":" + IntegerToString((int)OrderGetInteger(ORDER_MAGIC));
         json += "}";
      }
   }
   json += "]";
   WriteFile(FILE_ORDERS, json);
}

// ── Process pending commands (order placement) ──
void ProcessCommand() {
   // Check if command file exists before attempting to open it
   if (!FileIsExist(FILE_CMD)) return;

   // Wine filesystem sync is slow. Wait briefly for the write to complete
   // so we don't read a partial file. (Sleep is safe in OnTimer context.)
   Sleep(250);

   // ── Robust byte-wise read ─────────────────────────────────────────
   // Reading the file as raw bytes (FILE_BIN) avoids FILE_TXT / codepage
   // quirks that corrupt the UTF-8 JSON written by Python on the native
   // Mac / Wine build. The command payload is pure ASCII, so byte-wise
   // decoding is exact.
   string content = "";
   int h = FileOpen(FILE_CMD, FILE_READ|FILE_BIN, 0, CP_UTF8);
   if (h != INVALID_HANDLE) {
      while (!FileIsEnding(h)) {
         int b = FileReadInteger(h, 1);
         if (FileIsEnding(h)) break;   // don't append the EOF marker
         // Skip NUL bytes / UTF-16 BOM remnants (Wine filesystem quirks)
         if (b == 0 || b == 0xFF || b == 0xFE) continue;
         content += CharToString((uchar)b);
      }
      FileClose(h);
   }

   if (StringLen(content) < 20) { WriteCmdResult(-1, "cmd_too_short"); return; }
   string action = GetJsonValue(content, "action");
   if (action == "") { WriteCmdResult(-1, "parse_failed"); return; }


   // ── place_limit command ──
   if (action == "place_limit") {
      string symbol = GetJsonValue(content, "symbol");
      string order_type = GetJsonValue(content, "type");
      double price = StringToDouble(GetJsonValue(content, "price"));
      double volume = StringToDouble(GetJsonValue(content, "volume"));
      string comment = GetJsonValue(content, "comment");
      int magic = (int)StringToInteger(GetJsonValue(content, "magic"));
      if (magic == 0) magic = 123456;
      // Sanity check — if numeric parsing failed, report it clearly
      if (price <= 0 || volume <= 0) {
         WriteCmdResult(-3, "bad_parse price=" + DoubleToString(price, 2)
                       + " vol=" + DoubleToString(volume, 2)
                       + " type=[" + order_type + "]");
         FileDelete(FILE_CMD);
         return;
      }
      // Make sure we write ticks for this symbol too
      if (StringLen(symbol) > 0) EnsureSymbol(symbol);

      // If the requested symbol isn't available in this terminal, substitute
      // a matching one (e.g. requested "XAUUSD.r" but broker uses "XAUUSD").
      string original_symbol = symbol;
      if (StringLen(symbol) > 0 && !SymbolSelect(symbol, true)) {
         string alt = FindUsableSymbol(symbol);
         if (StringLen(alt) > 0) {
            Print("🔀 Symbol fallback: ", original_symbol, " -> ", alt);
            symbol = alt;
         }
      }

      // Normalize volume to the symbol's valid min/step (e.g. min 0.10).
      double raw_volume = volume;
      volume = NormalizeVolume(symbol, volume);
      if (volume != raw_volume)
         Print("🔧 Volume adjusted: ", DoubleToString(raw_volume, 2), " -> ", DoubleToString(volume, 2),
               " (spec min=", DoubleToString(SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN), 2),
               " step=", DoubleToString(SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP), 2),
               " max=", DoubleToString(SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX), 2), ")");

      ENUM_ORDER_TYPE mt_type = (order_type == "buy_limit") ? ORDER_TYPE_BUY_LIMIT : ORDER_TYPE_SELL_LIMIT;
      MqlTradeRequest req = {};
      req.action = TRADE_ACTION_PENDING;
      req.symbol = symbol;
      req.volume = volume;
      req.type = mt_type;
      req.price = price;
      req.deviation = 5;
      req.magic = magic;
      req.comment = comment;
      req.type_time = ORDER_TIME_GTC;
      // Use ORDER_FILLING_RETURN for pending orders — IOC is incompatible
      // with limit orders on most brokers and causes instant rejection.
      req.type_filling = ORDER_FILLING_RETURN;

      MqlTradeResult result = {};
      bool sent = OrderSend(req, result);

      string res_comment = result.comment;
      // Append the volume actually used so the dashboard can show it
      if (volume != raw_volume)
         res_comment += " (vol " + DoubleToString(raw_volume, 2) + "->" + DoubleToString(volume, 2) + ")";
      WriteCmdResult(result.retcode, res_comment, result.order, symbol);
      // Only delete command AFTER result was written
      FileDelete(FILE_CMD);
      return;
   }

   // ── close_positions command ──
   if (action == "close_positions") {
      string symbol = GetJsonValue(content, "symbol");
      int magic = (int)StringToInteger(GetJsonValue(content, "magic"));
      if (magic == 0) magic = 123456;

      int closed = 0, cancelled = 0;

      // Close positions
      int total = PositionsTotal();
      for (int i = total - 1; i >= 0; i--) {
         ulong ticket = PositionGetTicket(i);
         if (PositionSelectByTicket(ticket)) {
            if (magic > 0 && (int)PositionGetInteger(POSITION_MAGIC) != magic) continue;
            if (symbol != "" && PositionGetString(POSITION_SYMBOL) != symbol) continue;

            MqlTradeRequest req = {};
            req.action = TRADE_ACTION_DEAL;
            req.symbol = PositionGetString(POSITION_SYMBOL);
            req.volume = PositionGetDouble(POSITION_VOLUME);
            req.type = ((ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;
            req.position = PositionGetInteger(POSITION_TICKET);
            req.price = (req.type == ORDER_TYPE_SELL) ? SymbolInfoDouble(req.symbol, SYMBOL_BID) : SymbolInfoDouble(req.symbol, SYMBOL_ASK);
            req.deviation = 10;
            req.magic = magic;
            req.comment = "GridBotClose";
            req.type_filling = ORDER_FILLING_RETURN;

            MqlTradeResult result = {};
            bool sent = OrderSend(req, result);
            if (result.retcode == TRADE_RETCODE_DONE) closed++;
         }
      }

      // Delete pending orders
      total = OrdersTotal();
      for (int i = total - 1; i >= 0; i--) {
         ulong ticket = OrderGetTicket(i);
         if (OrderSelect(ticket)) {
            if (magic > 0 && (int)OrderGetInteger(ORDER_MAGIC) != magic) continue;
            if (symbol != "" && OrderGetString(ORDER_SYMBOL) != symbol) continue;

            MqlTradeRequest req = {};
            req.action = TRADE_ACTION_REMOVE;
            req.order = OrderGetInteger(ORDER_TICKET);
            MqlTradeResult result = {};
            bool sent = OrderSend(req, result);
            if (result.retcode == TRADE_RETCODE_DONE) cancelled++;
         }
      }

      string res_json = "{";
      res_json += "\"closed_positions\":" + IntegerToString(closed) + ",";
      res_json += "\"cancelled_orders\":" + IntegerToString(cancelled);
      res_json += "}";
      WriteFile(FILE_CMD_RESULT, res_json);

      // Only delete command AFTER result was written
      FileDelete(FILE_CMD);
      return;
   }

   // ── cancel_order command ──
   if (action == "cancel_order") {
      string symbol = GetJsonValue(content, "symbol");
      string price_or_ticket = GetJsonValue(content, "price_or_ticket");
      int magic = (int)StringToInteger(GetJsonValue(content, "magic"));
      if (magic == 0) magic = 123456;

      int cancelled = 0;
      double target_price = StringToDouble(price_or_ticket);
      bool by_price = (target_price > 0);
      int total = OrdersTotal();
      for (int i = total - 1; i >= 0; i--) {
         ulong ticket = OrderGetTicket(i);
         if (!OrderSelect(ticket)) continue;
         if (magic > 0 && (int)OrderGetInteger(ORDER_MAGIC) != magic) continue;
         if (symbol != "" && OrderGetString(ORDER_SYMBOL) != symbol) continue;
         bool match = false;
         if (by_price) {
            double oprice = OrderGetDouble(ORDER_PRICE_OPEN);
            if (MathAbs(oprice - target_price) < 0.005) match = true;
         } else if (price_or_ticket != "") {
            if (IntegerToString((int)OrderGetInteger(ORDER_TICKET)) == price_or_ticket) match = true;
         }
         if (!match) continue;
         MqlTradeRequest req = {};
         req.action = TRADE_ACTION_REMOVE;
         req.order = OrderGetInteger(ORDER_TICKET);
         MqlTradeResult result = {};
         OrderSend(req, result);
         if (result.retcode == TRADE_RETCODE_DONE) cancelled++;
      }
      WriteCmdResult(10009, "cancelled:" + IntegerToString(cancelled));
      FileDelete(FILE_CMD);
      return;
   }

   // Unknown action — write a result so the Python server never hangs
   string dbg = StringSubstr(content, 0, 140);
   StringReplace(dbg, "\"", "'");   // keep JSON in a single line safely
   WriteCmdResult(-2, "unknown_action:" + action + " content=[" + dbg + "]");
   FileDelete(FILE_CMD);
}

// ── Simple JSON string/number value extractor (robust) ──────────────
// Handles both "key":"value" and "key": value (with/without spaces).
string GetJsonValue(string json, string key) {
   string search = "\"" + key + "\"";
   int pos = StringFind(json, search);
   if (pos < 0) return "";
   // Find the colon that belongs to this key
   int colon = StringFind(json, ":", pos + StringLen(key) + 2);
   if (colon < 0) return "";
   // Skip whitespace after the colon
   int vstart = colon + 1;
   int jsonlen = StringLen(json);
   while (vstart < jsonlen && StringGetCharacter(json, vstart) == ' ') vstart++;
   if (vstart >= jsonlen) return "";
   // Quoted string value
   if (StringGetCharacter(json, vstart) == '"') {
      int vend = StringFind(json, "\"", vstart + 1);
      if (vend < 0) return "";
      return StringSubstr(json, vstart + 1, vend - vstart - 1);
   }
   // Numeric value — read until comma or closing brace
   int v = vstart;
   while (v < jsonlen) {
      ushort ch = StringGetCharacter(json, v);
      if (ch == ',' || ch == '}') break;
      v++;
   }
   string num = StringTrimRight(StringSubstr(json, vstart, v - vstart));
   return num;
}
//+------------------------------------------------------------------+