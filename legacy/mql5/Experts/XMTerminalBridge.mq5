#property strict

#include <BridgeTypes.mqh>

input string InboundFileName = "inbound\\control_flags.txt";
input string OutboundFileName = "outbound\\terminal_status.txt";
input int HeartbeatSeconds = 2;

BridgeFlags g_flags;

void ResetFlags()
  {
   g_flags.allow_new_entries = true;
   g_flags.close_only = false;
   g_flags.kill_switch = false;
   g_flags.operator_note = "";
  }

void LoadControlFlags()
  {
   int handle = FileOpen(InboundFileName, FILE_READ | FILE_TXT | FILE_ANSI);
   if(handle == INVALID_HANDLE)
      return;

   while(!FileIsEnding(handle))
     {
      string line = FileReadString(handle);
      int split = StringFind(line, "=");
      if(split < 0)
         continue;

      string key = TrimCopy(StringSubstr(line, 0, split));
      string value = TrimCopy(StringSubstr(line, split + 1));

      if(key == "allow_new_entries")
         g_flags.allow_new_entries = TextBool(value);
      else if(key == "close_only")
         g_flags.close_only = TextBool(value);
      else if(key == "kill_switch")
         g_flags.kill_switch = TextBool(value);
      else if(key == "operator_note")
         g_flags.operator_note = value;
     }

   FileClose(handle);
  }

void WriteTerminalStatus()
  {
   int handle = FileOpen(OutboundFileName, FILE_WRITE | FILE_TXT | FILE_ANSI);
   if(handle == INVALID_HANDLE)
      return;

   MqlTick tick;
   bool has_tick = SymbolInfoTick(_Symbol, tick);

   FileWrite(handle, "timestamp=" + TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS));
   FileWrite(handle, "symbol=" + _Symbol);
   FileWrite(handle, "connected=" + BoolText((bool)TerminalInfoInteger(TERMINAL_CONNECTED)));
   FileWrite(handle, "trade_allowed=" + BoolText((bool)TerminalInfoInteger(TERMINAL_TRADE_ALLOWED)));
   FileWrite(handle, "account_login=" + IntegerToString((int)AccountInfoInteger(ACCOUNT_LOGIN)));
   FileWrite(handle, "server=" + AccountInfoString(ACCOUNT_SERVER));
   FileWrite(handle, "balance=" + DoubleToString(AccountInfoDouble(ACCOUNT_BALANCE), 2));
   FileWrite(handle, "equity=" + DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY), 2));
   FileWrite(handle, "allow_new_entries=" + BoolText(g_flags.allow_new_entries));
   FileWrite(handle, "close_only=" + BoolText(g_flags.close_only));
   FileWrite(handle, "kill_switch=" + BoolText(g_flags.kill_switch));
   FileWrite(handle, "operator_note=" + g_flags.operator_note);

   if(has_tick)
     {
      FileWrite(handle, "bid=" + DoubleToString(tick.bid, _Digits));
      FileWrite(handle, "ask=" + DoubleToString(tick.ask, _Digits));
     }

   FileClose(handle);
  }

int OnInit()
  {
   ResetFlags();
   EventSetTimer(HeartbeatSeconds);
   WriteTerminalStatus();
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
  }

void OnTimer()
  {
   LoadControlFlags();
   WriteTerminalStatus();
  }
