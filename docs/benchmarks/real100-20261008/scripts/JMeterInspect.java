import java.io.*;
import java.nio.file.*;
import java.util.*;
import java.util.regex.*;
import org.apache.jmeter.util.JMeterUtils;
import org.apache.jmeter.save.SaveService;
import com.jayway.jsonpath.JsonPath;
import groovy.json.JsonSlurper;
import groovy.json.JsonOutput;

public class JMeterInspect {
 public static void main(String[] args) throws Exception {
  String home=args[0]; JMeterUtils.setJMeterHome(home);
  JMeterUtils.loadJMeterProperties(home+"/bin/jmeter.properties");SaveService.loadProperties();
  List<Map<String,Object>> output=new ArrayList<>();
  List<Map> jobs=(List<Map>)new JsonSlurper().parse(new File(args[1]));
  for(Map job:jobs){Map<String,Object> row=new LinkedHashMap<>();row.put("id",job.get("id"));
   try {
    if(job.containsKey("jmx")){SaveService.loadTree(new File((String)job.get("jmx")));row.put("loaded",true);}
    else if("jsonpath".equals(job.get("kind"))){Object value=JsonPath.read((String)job.get("body"),(String)job.get("expression"));row.put("resolved",value);}
    else {Matcher matcher=Pattern.compile((String)job.get("expression")).matcher((String)job.get("body"));row.put("matched",matcher.find());if(matcher.find(0))row.put("resolved",matcher.group(1));}
    row.put("success",true);
   }catch(Exception e){row.put("success",false);row.put("error",e.getClass().getName()+": "+e.getMessage());}
   output.add(row);
  }
  Files.writeString(Path.of(args[2]),JsonOutput.toJson(output));
 }
}
