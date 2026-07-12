//+------------------------------------------------------------------+
//|                                              mt5_bridge_ea.mq5   |
//|  Bridge between MT5 and Python via JSON files (Mac-compatible)   |
//+------------------------------------------------------------------+
#property strict
#property version   "1.00"

// ── File names (written to MT5 Files folder) ──
#define FILE_ACCOUNT   "mt5_account.json"
#define FILE_TICK      "mt5_tick.json"
#define FILE_POSITIONS "mt5_positions.json"
#define FILE_ORDERS    "mt5_orders.json"
#define FILE_CMD       "mt5_cmd.json"
#define FILE_CMD_RESULT "mt5_cmd_result.json"

string g_symbols[] = {"XAUUSD", "EURUSD", "GBPUSD", "USDJPY"};
int g_timer_sec = 1;

//+------------------------------------------------------------------+
int OnInit() {
   EventSetTimer(g_timer_sec);
   Print("✅ mt5_bridge_ea started, writing files every ", g_timer_sec, " sec");
   return(INIT_SUCCEEDED);
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
   WriteAccount();
   WriteTick(g_symbols);
   WritePositions();
   WriteOrders();
   ProcessCommand();
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
   int h = FileOpen(FILE_CMD, FILE_TXT|FILE_READ, 0, CP_UTF8);
   if (h == INVALID_HANDLE) return;

   string content = "";
   while (!FileIsEnding(h))
      content += FileReadString(h);
   FileClose(h);

   // Delete command file so we don't re-process
   FileDelete(FILE_CMD);

   if (StringLen(content) < 10) return;

   // Parse simple JSON command
   // Expected: {"action":"place_limit","symbol":"XAUUSD","type":"buy_limit","price":1950.0,"volume":0.01,"comment":"Bridge","magic":123456}
   string action = GetJsonValue(content, "action");
   if (action == "place_limit") {
      string symbol = GetJsonValue(content, "symbol");
      string order_type = GetJsonValue(content, "type");
      double price = StringToDouble(GetJsonValue(content, "price"));
      double volume = StringToDouble(GetJsonValue(content, "volume"));
      string comment = GetJsonValue(content, "comment");
      int magic = (int)StringToInteger(GetJsonValue(content, "magic"));
      if (magic == 0) magic = 123456;

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
      req.type_filling = ORDER_FILLING_IOC;

      MqlTradeResult result = {};
      bool sent = OrderSend(req, result);

      string res_json = "{";
      res_json += "\"retcode\":" + IntegerToString(result.retcode) + ",";
      res_json += "\"ticket\":" + IntegerToString(result.order) + ",";
      res_json += "\"comment\":\"" + result.comment + "\"";
      res_json += "}";
      WriteFile(FILE_CMD_RESULT, res_json);
   }

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
            req.type_filling = ORDER_FILLING_IOC;

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
   }
}

// ── Simple JSON string value extractor (no nested objects) ──
string GetJsonValue(string json, string key) {
   string search = "\"" + key + "\":\"";
   int pos = StringFind(json, search);
   if (pos >= 0) {
      int start = pos + StringLen(search);
      int end = StringFind(json, "\"", start);
      if (end > start) return StringSubstr(json, start, end - start);
   }
   // Try numeric value
   search = "\"" + key + "\":";
   pos = StringFind(json, search);
   if (pos >= 0) {
      int start = pos + StringLen(search);
      // Find end (comma or closing brace)
      string rest = StringSubstr(json, start);
      int end = StringFind(rest, ",");
      if (end < 0) end = StringFind(rest, "}");
      if (end > 0) {
         string val = StringSubstr(rest, 0, end);
         // Trim whitespace & quotes
         val = StringTrimLeft(val);
         val = StringTrimRight(val);
         if (StringGetCharacter(val, 0) == '"') val = StringSubstr(val, 1, StringLen(val)-2);
         return val;
      }
   }
   return "";
}
//+------------------------------------------------------------------+