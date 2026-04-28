#property strict

#include <bridge_common.mqh>

input string          TradeSymbol = "";
input ENUM_TIMEFRAMES SnapshotTimeframe = PERIOD_M5;
input int             SnapshotBars = 30;
input int             TimerSeconds = 2;
input int             MaxQuoteAgeSeconds = 10;
input int             MaxPriceDeviationPoints = 20;
input string          InboundDirectory = "inbound\\";
input string          OutboundDirectory = "outbound\\";
input string          ProcessedDecisionLog = "outbound\\processed_decisions.log";
input string          AuditLogFile = "outbound\\bridge_audit.log";

string ActiveSymbol()
  {
   if(TradeSymbol != "")
      return TradeSymbol;
   return _Symbol;
  }

string TimeframeLabel(ENUM_TIMEFRAMES timeframe)
  {
   switch(timeframe)
     {
      case PERIOD_M1: return "M1";
      case PERIOD_M5: return "M5";
      case PERIOD_M15: return "M15";
      case PERIOD_M30: return "M30";
      case PERIOD_H1: return "H1";
      case PERIOD_H4: return "H4";
      case PERIOD_D1: return "D1";
     }
   return EnumToString(timeframe);
  }

int EffectivePriceDeviationPoints(string symbol)
  {
   if(StringFind(symbol, "BTC", 0) >= 0)
      return MathMax(MaxPriceDeviationPoints, 5000);
   if(StringFind(symbol, "ETH", 0) >= 0)
      return MathMax(MaxPriceDeviationPoints, 1000);
   return MaxPriceDeviationPoints;
  }

void BridgeAudit(string line)
  {
   string stamped = BridgeIsoUtc(TimeGMT()) + " | " + line;
   BridgeAppendLine(AuditLogFile, stamped);
  }

bool DecisionAlreadyProcessed(string decision_id)
  {
   string content = "";
   if(!BridgeReadTextFile(ProcessedDecisionLog, content))
      return false;

   string lines[];
   int count = StringSplit(content, '\n', lines);
   for(int index = 0; index < count; index++)
     {
      string line = BridgeTrim(lines[index]);
      if(line == "")
         continue;
      if(StringFind(line, decision_id + "|", 0) == 0)
         return true;
     }
   return false;
  }

void MarkDecisionProcessed(string decision_id, string status)
  {
   BridgeAppendLine(
      ProcessedDecisionLog,
      decision_id + "|" + status + "|" + BridgeIsoUtc(TimeGMT())
   );
  }

string BuildTerminalStatusJson(string symbol, MqlTick &tick)
  {
   bool connected = (bool)TerminalInfoInteger(TERMINAL_CONNECTED);
   bool trade_allowed = (bool)TerminalInfoInteger(TERMINAL_TRADE_ALLOWED);
   bool expert_enabled = (bool)MQLInfoInteger(MQL_TRADE_ALLOWED);
   bool dlls_allowed = (bool)MQLInfoInteger(MQL_DLLS_ALLOWED);
   bool trade_context_busy = false;
   int quote_age_seconds = 0;
   if(tick.time > 0)
      quote_age_seconds = (int)(TimeGMT() - (datetime)tick.time);

   string session_status = "CONNECTED";
   if(!connected)
      session_status = "DISCONNECTED";
   else if(!trade_allowed || !expert_enabled)
      session_status = "TRADE_DISABLED";

   return StringFormat(
      "{"
      "\"connected\":%s,"
      "\"trade_allowed\":%s,"
      "\"expert_enabled\":%s,"
      "\"dlls_allowed\":%s,"
      "\"trade_context_busy\":%s,"
      "\"quote_age_seconds\":%d,"
      "\"session_status\":\"%s\","
      "\"server\":\"%s\","
      "\"company\":\"%s\","
      "\"ping_ms\":%d"
      "}",
      BridgeBool(connected),
      BridgeBool(trade_allowed),
      BridgeBool(expert_enabled),
      BridgeBool(dlls_allowed),
      BridgeBool(trade_context_busy),
      quote_age_seconds,
      BridgeJsonEscape(session_status),
      BridgeJsonEscape(AccountInfoString(ACCOUNT_SERVER)),
      BridgeJsonEscape(TerminalInfoString(TERMINAL_COMPANY)),
      (int)TerminalInfoInteger(TERMINAL_PING_LAST)
   );
  }

int CollectRecentBars(string symbol, ENUM_TIMEFRAMES timeframe, int requested, BridgeBar &bars[])
  {
   ArrayResize(bars, 0);
   MqlRates rates[];
   ArraySetAsSeries(rates, false);
   int copied = CopyRates(symbol, timeframe, 0, requested, rates);
   if(copied <= 0)
      return 0;

   ArrayResize(bars, copied);
   for(int index = 0; index < copied; index++)
     {
      bars[index].timestamp = BridgeIsoUtc((datetime)rates[index].time);
      bars[index].timestamp_epoch = (int)rates[index].time;
      bars[index].open = rates[index].open;
      bars[index].high = rates[index].high;
      bars[index].low = rates[index].low;
      bars[index].close = rates[index].close;
      bars[index].volume = (double)rates[index].tick_volume;
     }
   return copied;
  }

int CollectOpenPositions(string symbol, BridgePosition &positions[])
  {
   ArrayResize(positions, 0);
   int total = PositionsTotal();
   for(int index = 0; index < total; index++)
     {
      ulong ticket = PositionGetTicket(index);
      if(ticket == 0 || !PositionSelectByTicket(ticket))
         continue;
      string position_symbol = PositionGetString(POSITION_SYMBOL);
      if(position_symbol != symbol)
         continue;

      int next_slot = ArraySize(positions);
      ArrayResize(positions, next_slot + 1);
      positions[next_slot].ticket = (long)ticket;
      positions[next_slot].symbol = position_symbol;
      positions[next_slot].direction =
         (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? "BUY" : "SELL";
      positions[next_slot].volume = PositionGetDouble(POSITION_VOLUME);
      positions[next_slot].open_price = PositionGetDouble(POSITION_PRICE_OPEN);
      positions[next_slot].stop_loss = PositionGetDouble(POSITION_SL);
      positions[next_slot].has_stop_loss = positions[next_slot].stop_loss > 0.0;
      positions[next_slot].take_profit = PositionGetDouble(POSITION_TP);
      positions[next_slot].has_take_profit = positions[next_slot].take_profit > 0.0;
      positions[next_slot].profit = PositionGetDouble(POSITION_PROFIT);
     }
   return ArraySize(positions);
  }

void PublishStateSnapshot()
  {
   string symbol = ActiveSymbol();
   MqlTick tick;
   ZeroMemory(tick);
   SymbolInfoTick(symbol, tick);

   BridgeBar bars[];
   BridgePosition positions[];
   CollectRecentBars(symbol, SnapshotTimeframe, SnapshotBars, bars);
   CollectOpenPositions(symbol, positions);

   double bid = tick.bid;
   double ask = tick.ask;
   double spread_points = 0.0;
   if(bid > 0.0 && ask > 0.0)
      spread_points = (ask - bid) / _Point;

   string message_id = BridgeMessageId("state");
   string payload = BridgeStatusPayload(
      message_id,
      symbol,
      TimeframeLabel(SnapshotTimeframe),
      bid,
      ask,
      spread_points,
      bars,
      positions,
      AccountInfoDouble(ACCOUNT_BALANCE),
      AccountInfoDouble(ACCOUNT_EQUITY),
      AccountInfoDouble(ACCOUNT_MARGIN_FREE),
      BuildTerminalStatusJson(symbol, tick)
   );
   string file_name = OutboundDirectory + "state_" + message_id + ".json";
   if(BridgeWriteTextFile(file_name, payload))
      BridgeAudit("published_state " + message_id);
   else
      BridgeAudit("state_publish_failed " + message_id);
  }

bool ValidateDecisionEnvelope(BridgeDecision &decision, string &error_message)
  {
   error_message = "";
   string symbol = ActiveSymbol();
   if(decision.symbol != symbol)
     {
      error_message = "Decision symbol does not match active symbol.";
      return false;
     }
   if(decision.risk_pct < 0.0 || decision.risk_pct > 1.0)
     {
      error_message = "risk_pct is out of range.";
      return false;
     }
   if(decision.valid_for_seconds <= 0)
     {
      error_message = "valid_for_seconds must be positive.";
      return false;
     }
   if(BridgeActionIsOpen(decision.action) && (!decision.has_stop_loss || !decision.has_take_profit))
     {
      error_message = "Open actions require stop_loss and take_profit.";
      return false;
     }
   return true;
  }

bool CheckTradingEnvironment(string &error_message)
  {
   error_message = "";
   if(!(bool)TerminalInfoInteger(TERMINAL_CONNECTED))
     {
      error_message = "Terminal is disconnected.";
      return false;
     }
   if(!(bool)TerminalInfoInteger(TERMINAL_TRADE_ALLOWED))
     {
      error_message = "Terminal trading is disabled.";
      return false;
     }
   if(!(bool)MQLInfoInteger(MQL_TRADE_ALLOWED))
     {
      error_message = "Expert Advisor trading is disabled.";
      return false;
     }
   return true;
  }

bool OrderCheckAccepted(MqlTradeCheckResult &check)
  {
   int retcode = (int)check.retcode;
   return(retcode == 0 || retcode == TRADE_RETCODE_DONE || retcode == TRADE_RETCODE_DONE_PARTIAL);
  }

bool ClosePositionTicket(
   ulong ticket,
   double requested_volume,
   string symbol,
   string decision_id,
   MqlTick &tick,
   string &error_message,
   MqlTradeResult &result
)
  {
   error_message = "";
   if(!PositionSelectByTicket(ticket))
     {
      error_message = "Position not found.";
      return false;
     }

   ENUM_POSITION_TYPE position_type = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
   double position_volume = PositionGetDouble(POSITION_VOLUME);
   double close_volume = MathMin(position_volume, requested_volume);
   close_volume = BridgeNormalizeVolume(symbol, close_volume);
   if(close_volume <= 0.0)
     {
      error_message = "Close volume is invalid after normalization.";
      return false;
     }

   MqlTradeRequest request;
   ZeroMemory(request);
   ZeroMemory(result);
   request.action = TRADE_ACTION_DEAL;
   request.symbol = symbol;
   request.position = ticket;
   request.volume = close_volume;
   request.deviation = EffectivePriceDeviationPoints(symbol);
   request.magic = 450001;
   request.type_filling = BridgeResolveFillingMode(symbol);
   request.comment = "XMBridgeEA:" + decision_id;

   if(position_type == POSITION_TYPE_BUY)
     {
      request.type = ORDER_TYPE_SELL;
      request.price = tick.bid;
     }
   else
     {
      request.type = ORDER_TYPE_BUY;
      request.price = tick.ask;
     }

   MqlTradeCheckResult check;
   ZeroMemory(check);
   if(!OrderCheck(request, check))
     {
      error_message = "OrderCheck failed for close request.";
      return false;
     }
   if(!OrderCheckAccepted(check))
     {
      error_message = "OrderCheck rejected close request: " + check.comment;
      return false;
     }
   if(!OrderSend(request, result))
     {
      error_message = "OrderSend failed for close request.";
      return false;
     }
   return true;
  }

bool ExecuteCloseOrReduce(
   BridgeDecision &decision,
   string &status,
   string &reason,
   string &broker_order_id,
   double &fill_price,
   double &filled_volume,
   int &retcode,
   int &error_code
)
  {
   status = "REJECTED";
   reason = "No positions available to close.";
   broker_order_id = "";
   fill_price = 0.0;
   filled_volume = 0.0;
   retcode = 0;
   error_code = 0;

   string symbol = ActiveSymbol();
   MqlTick tick;
   if(!BridgeFreshTick(symbol, MaxQuoteAgeSeconds, tick, reason))
     {
      status = "REJECTED";
      error_code = GetLastError();
      return false;
     }

   double total_volume = 0.0;
   int total_positions = PositionsTotal();
   for(int index = 0; index < total_positions; index++)
     {
      ulong ticket = PositionGetTicket(index);
      if(ticket == 0 || !PositionSelectByTicket(ticket))
         continue;
      if(PositionGetString(POSITION_SYMBOL) != symbol)
         continue;
      total_volume += PositionGetDouble(POSITION_VOLUME);
     }
   if(total_volume <= 0.0)
      return false;

   double target_volume = total_volume;
   if(decision.action == "REDUCE")
      target_volume = total_volume * decision.risk_pct;

   double remaining = MathMax(0.0, target_volume);
   for(int pos_index = 0; pos_index < total_positions && remaining > 0.0; pos_index++)
     {
      ulong ticket = PositionGetTicket(pos_index);
      if(ticket == 0 || !PositionSelectByTicket(ticket))
         continue;
      if(PositionGetString(POSITION_SYMBOL) != symbol)
         continue;

      double position_volume = PositionGetDouble(POSITION_VOLUME);
      double close_volume = MathMin(position_volume, remaining);
      MqlTradeResult result;
      string close_error = "";
      if(!ClosePositionTicket(ticket, close_volume, symbol, decision.decision_id, tick, close_error, result))
        {
         status = "REJECTED";
         reason = close_error;
         retcode = (int)result.retcode;
         error_code = GetLastError();
         return false;
        }
      remaining -= close_volume;
      broker_order_id = IntegerToString((int)result.order);
      fill_price = result.price;
      filled_volume += close_volume;
      retcode = (int)result.retcode;
     }

   if(filled_volume <= 0.0)
     {
      reason = "Close or reduce produced zero fill volume.";
      status = "INVALID_FILL";
      return false;
     }

   status = "FILLED";
   reason = (decision.action == "CLOSE") ? "Positions closed." : "Positions reduced.";
   return true;
  }

bool ExecuteOpenDecision(
   BridgeDecision &decision,
   string &status,
   string &reason,
   string &broker_order_id,
   double &fill_price,
   double &filled_volume,
   int &retcode,
   int &error_code
)
  {
   string symbol = ActiveSymbol();
   MqlTick tick;
   if(!BridgeFreshTick(symbol, MaxQuoteAgeSeconds, tick, reason))
     {
      status = "REJECTED";
      error_code = GetLastError();
      return false;
     }

   if(!BridgeValidateStops(symbol, decision.action, tick, decision.stop_loss, decision.take_profit, reason))
     {
      status = "REJECTED";
      return false;
     }

   double entry_price = tick.ask;
   ENUM_ORDER_TYPE order_type = ORDER_TYPE_BUY;
   if(decision.action == "OPEN_SHORT")
     {
      entry_price = tick.bid;
      order_type = ORDER_TYPE_SELL;
     }

   string volume_error = "";
   double volume = BridgeVolumeFromRiskPct(
      symbol,
      entry_price,
      decision.stop_loss,
      decision.risk_pct,
      AccountInfoDouble(ACCOUNT_EQUITY),
      volume_error
   );
   if(volume <= 0.0)
     {
      status = "REJECTED";
      reason = volume_error;
      return false;
     }

   MqlTradeRequest request;
   ZeroMemory(request);
   request.action = TRADE_ACTION_DEAL;
   request.symbol = symbol;
   request.volume = volume;
   request.type = order_type;
   request.price = entry_price;
   request.sl = decision.stop_loss;
   request.tp = decision.take_profit;
   request.deviation = EffectivePriceDeviationPoints(symbol);
   request.magic = 450001;
   request.type_filling = BridgeResolveFillingMode(symbol);
   request.comment = "XMBridgeEA:" + decision.decision_id;

   MqlTradeCheckResult check;
   ZeroMemory(check);
   if(!OrderCheck(request, check))
     {
      status = "REJECTED";
      reason = "OrderCheck failed for open request.";
      error_code = GetLastError();
      return false;
     }
   if(!OrderCheckAccepted(check))
     {
      status = "REJECTED";
      reason = "OrderCheck rejected open request: " + check.comment;
      retcode = (int)check.retcode;
      return false;
     }

   MqlTradeResult result;
   ZeroMemory(result);
   if(!OrderSend(request, result))
     {
      status = "ERROR";
      reason = "OrderSend failed for open request.";
      error_code = GetLastError();
      retcode = (int)result.retcode;
      return false;
     }

   retcode = (int)result.retcode;
   broker_order_id = IntegerToString((int)result.order);
   fill_price = result.price;
   filled_volume = volume;

   if(result.retcode == TRADE_RETCODE_DONE || result.retcode == TRADE_RETCODE_DONE_PARTIAL)
     {
      if(fill_price <= 0.0 || filled_volume <= 0.0)
        {
         status = "INVALID_FILL";
         reason = "Broker accepted the order but returned an invalid fill.";
         return false;
        }
      status = (result.retcode == TRADE_RETCODE_DONE_PARTIAL) ? "PARTIAL" : "FILLED";
      reason = result.comment;
      return true;
     }

   status = "REJECTED";
   reason = result.comment;
   return false;
  }

void EmitExecutionResult(
   BridgeDecision &decision,
   string status,
   string reason,
   string broker_order_id,
   double fill_price,
   double filled_volume,
   int retcode,
   int error_code
)
  {
   string message_id = BridgeMessageId("execution");
   string payload = BridgeExecutionPayload(
      message_id,
      decision.decision_id,
      decision.state_message_id,
      decision.symbol,
      status,
      reason,
      broker_order_id,
      fill_price,
      filled_volume,
      retcode,
      error_code
   );
   string file_name = OutboundDirectory + "execution_" + message_id + ".json";
   if(BridgeWriteTextFile(file_name, payload))
      BridgeAudit("execution_result " + decision.decision_id + " " + status);
   else
      BridgeAudit("execution_result_failed " + decision.decision_id + " " + status);
  }

void ProcessDecisionFile(string file_name)
  {
   string raw = "";
   if(!BridgeReadTextFile(file_name, raw))
      return;

   BridgeDecision decision;
   string parse_error = "";
   if(!BridgeParseDecision(raw, decision, parse_error))
     {
      BridgeAudit("decision_parse_failed " + file_name + " " + parse_error);
      return;
     }

   if(DecisionAlreadyProcessed(decision.decision_id))
     {
      EmitExecutionResult(
         decision,
         "DUPLICATE_IGNORED",
         "Decision already processed.",
         "",
         0.0,
         0.0,
         0,
         0
      );
      return;
     }

   string validation_error = "";
   if(!ValidateDecisionEnvelope(decision, validation_error))
     {
      EmitExecutionResult(decision, "REJECTED", validation_error, "", 0.0, 0.0, 0, 0);
      MarkDecisionProcessed(decision.decision_id, "REJECTED");
      return;
     }

   if(BridgeDecisionIsStale(decision))
     {
      EmitExecutionResult(
         decision,
         "STALE_REJECTED",
         "Decision exceeded valid_for_seconds.",
         "",
         0.0,
         0.0,
         0,
         0
      );
      MarkDecisionProcessed(decision.decision_id, "STALE_REJECTED");
      return;
     }

   if(BridgeActionIsPassive(decision.action))
     {
      string passive_status = (decision.action == "BLOCK") ? "BLOCKED" : "RECEIVED";
      string passive_reason = (decision.action == "BLOCK") ? "Execution blocked by Python policy." : "No execution requested.";
      EmitExecutionResult(decision, passive_status, passive_reason, "", 0.0, 0.0, 0, 0);
      MarkDecisionProcessed(decision.decision_id, passive_status);
      return;
     }

   string environment_error = "";
   if(!CheckTradingEnvironment(environment_error))
     {
      EmitExecutionResult(
         decision,
         "TERMINAL_DISCONNECTED",
         environment_error,
         "",
         0.0,
         0.0,
         0,
         GetLastError()
      );
      MarkDecisionProcessed(decision.decision_id, "TERMINAL_DISCONNECTED");
      return;
     }

   string status = "ERROR";
   string reason = "Unknown execution outcome.";
   string broker_order_id = "";
   double fill_price = 0.0;
   double filled_volume = 0.0;
   int retcode = 0;
   int error_code = 0;
   bool success = false;

   if(decision.action == "OPEN_LONG" || decision.action == "OPEN_SHORT")
      success = ExecuteOpenDecision(
         decision,
         status,
         reason,
         broker_order_id,
         fill_price,
         filled_volume,
         retcode,
         error_code
      );
   else if(decision.action == "CLOSE" || decision.action == "REDUCE")
      success = ExecuteCloseOrReduce(
         decision,
         status,
         reason,
         broker_order_id,
         fill_price,
         filled_volume,
         retcode,
         error_code
      );
   else
     {
      status = "REJECTED";
      reason = "Unsupported action.";
     }

   EmitExecutionResult(
      decision,
      status,
      reason,
      broker_order_id,
      fill_price,
      filled_volume,
      retcode,
      error_code
   );
   MarkDecisionProcessed(decision.decision_id, status);
   if(success)
      BridgeAudit("decision_executed " + decision.decision_id + " " + status);
   else
      BridgeAudit("decision_failed " + decision.decision_id + " " + status + " " + reason);
  }

void ProcessInboundDecisions()
  {
   string file_name = "";
   long handle = FileFindFirst(InboundDirectory + "decision_*.json", file_name);
   if(handle == INVALID_HANDLE)
      return;

   do
     {
      ProcessDecisionFile(InboundDirectory + file_name);
     }
   while(FileFindNext(handle, file_name));

   FileFindClose(handle);
  }

int OnInit()
  {
   EventSetTimer(TimerSeconds);
   BridgeAudit("XMBridgeEA initialized for symbol " + ActiveSymbol());
   PublishStateSnapshot();
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   BridgeAudit("XMBridgeEA deinitialized reason=" + IntegerToString(reason));
  }

void OnTimer()
  {
   PublishStateSnapshot();
   ProcessInboundDecisions();
  }
