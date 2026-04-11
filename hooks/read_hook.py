  # hooks/read_hook.py                                                                                                                                 
  import json     
  import sys

  data = json.load(sys.stdin)                                                                                                                          
  read_path = data.get("tool_input", {}).get("file_path", "") or \
              data.get("tool_input", {}).get("path", "")                                                                                               
                                                                                                                                                       
  if ".env" in read_path:
      print("You cannot read the .env file", file=sys.stderr)                                                                                          
      sys.exit(2)                                                                                                                                      
   
  Then in your project's .claude/settings.local.json:                                                                                                  
                  
